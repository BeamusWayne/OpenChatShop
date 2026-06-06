"""Integration tests for the orchestrator's Multi-Agent triage path (feat-051).

The TriageRouter is opt-in via set_triage_router. When injected, each turn is
triaged after intent classification:
  * escalation -> short-circuit to the existing transfer (handoff) path;
  * routable intent -> tools scoped to the domain specialist (+ its prompt);
  * anything else -> the normal flow.
When NOT injected the flow is byte-identical to before (covered by the whole
existing suite staying green); the router-off test here pins that locally.
"""
from __future__ import annotations

import pytest

from open_chat_shop.core.context import InMemoryContextManager
from open_chat_shop.core.domain_agents import build_default_agents
from open_chat_shop.core.orchestrator import DialogueOrchestrator
from open_chat_shop.core.security import SecurityGuard
from open_chat_shop.core.triage_router import TriageRouter
from open_chat_shop.core.types import Action, Intent, UserMessage

ALL_TOOLS = [
    "query_order", "query_logistics", "search_product", "check_refund_eligibility",
    "create_refund", "cancel_order", "modify_address", "handoff_to_human",
]


class _StubTool:
    def __init__(self, name: str) -> None:
        self.name = name


class _StubInjector:
    async def inject(self, intent, context):
        return [_StubTool(n) for n in ALL_TOOLS]


class _StubIntent:
    def __init__(self, name: str) -> None:
        self._name = name

    async def classify(self, message, context):
        return Intent(name=self._name, display_name=self._name, confidence=1.0, source="rule")


class _RecordingStrategy:
    def __init__(self) -> None:
        self.called = False
        self.tools_seen: list = []

    async def decide(self, intent, context, tools):
        self.called = True
        self.tools_seen = list(tools)
        return Action(type="reply", payload={"content": "好的"})


def _orch(intent_name: str, *, with_router: bool):
    strat = _RecordingStrategy()
    orch = DialogueOrchestrator(
        security_guard=SecurityGuard({}),
        context_manager=InMemoryContextManager(),
        intent_engine=_StubIntent(intent_name),
        tool_injector=_StubInjector(),
        strategy=strat,
    )
    if with_router:
        orch.set_triage_router(TriageRouter(build_default_agents()))
    return orch, strat


@pytest.mark.unit
class TestTriageIntegration:
    @pytest.mark.asyncio
    async def test_escalation_short_circuits_to_handoff(self) -> None:
        # Even with a routable intent (create_refund), an escalation message
        # must hand off — and the strategy must be skipped entirely.
        orch, strat = _orch("create_refund", with_router=True)
        resp = await orch.handle_message(
            UserMessage(session_id="e1", content="我要投诉你们！", channel="web")
        )
        assert resp.message_type == "transfer"
        assert strat.called is False

    @pytest.mark.asyncio
    async def test_routable_intent_scopes_to_its_domain(self) -> None:
        orch, strat = _orch("create_refund", with_router=True)
        resp = await orch.handle_message(
            UserMessage(session_id="r1", content="我要退款", channel="web")
        )
        assert resp.meta["triage_domain"] == "refund"
        # Strategy saw ONLY the refund specialist's tools, not all eight.
        assert {t.name for t in strat.tools_seen} == {
            "check_refund_eligibility", "create_refund", "cancel_order",
        }

    @pytest.mark.asyncio
    async def test_unrouted_intent_falls_back_unscoped(self) -> None:
        orch, strat = _orch("greeting", with_router=True)
        resp = await orch.handle_message(
            UserMessage(session_id="f1", content="你好呀", channel="web")
        )
        assert resp.meta["triage_domain"] == ""
        assert len(strat.tools_seen) == len(ALL_TOOLS)

    @pytest.mark.asyncio
    async def test_router_off_is_unchanged(self) -> None:
        # The feature flag: with no router, an escalation message is NOT handed
        # off — the normal strategy runs, exactly as before feat-051.
        orch, strat = _orch("create_refund", with_router=False)
        resp = await orch.handle_message(
            UserMessage(session_id="o1", content="我要投诉你们！", channel="web")
        )
        assert strat.called is True
        assert resp.meta["triage_domain"] == ""
