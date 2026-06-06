"""Regression tests for cost-governance wiring (audit HIGH-7).

Before this fix the orchestrator recorded fake cost data
(``model='unknown', prompt_tokens=0, completion_tokens=0``) on the reply
path and recorded *nothing* on the tool-result path, so the CostTracker
and the per-session budget guard ran on placeholder numbers.

These tests pin the wired behaviour:
  - both LLM call sites record the *real* token usage from response.usage;
  - the real model name is used (never the literal "unknown");
  - token usage is exposed on response.meta so BudgetMiddleware can consume
    the real value instead of a flat default_cost.
"""
from __future__ import annotations

import pytest

from open_chat_shop.core.context import InMemoryContextManager
from open_chat_shop.core.orchestrator import DialogueOrchestrator
from open_chat_shop.core.provider import MockProvider
from open_chat_shop.core.security import SecurityGuard
from open_chat_shop.core.types import (
    Action,
    Intent,
    SessionContext,
    UserMessage,
)
from open_chat_shop.observability.logging import CostTracker


def _bare_orchestrator(provider, cost_tracker=None) -> DialogueOrchestrator:
    """Orchestrator for direct helper calls (deps unused by _llm_enhance*)."""
    orch = DialogueOrchestrator(None, None, None, None, None)
    orch.set_provider(provider)
    if cost_tracker is not None:
        orch.set_cost_tracker(cost_tracker)
    return orch


def _ctx() -> SessionContext:
    return SessionContext(session_id="s1", user_id=None, channel="web")


# ---------------------------------------------------------------------------
# Reply path — _llm_enhance
# ---------------------------------------------------------------------------


class TestLlmEnhanceCost:
    @pytest.mark.asyncio
    async def test_records_real_token_usage(self) -> None:
        tracker = CostTracker()
        orch = _bare_orchestrator(MockProvider(), tracker)
        msg = await orch._llm_enhance(Action(type="reply", payload={"content": "hi"}), _ctx())
        summary = tracker.get_summary()
        # MockProvider reports prompt=10, completion=20, total=30.
        assert summary["total_requests"] == 1
        assert summary["total_tokens"] == 30
        assert msg is not None
        assert msg.meta.get("token_usage") == 30

    @pytest.mark.asyncio
    async def test_uses_real_model_name_not_unknown(self) -> None:
        tracker = CostTracker()
        orch = _bare_orchestrator(MockProvider(), tracker)
        await orch._llm_enhance(Action(type="reply", payload={"content": "hi"}), _ctx())
        by_model = tracker.get_summary()["by_model"]
        assert "unknown" not in by_model
        assert "mock" in by_model  # MockProvider.name

    @pytest.mark.asyncio
    async def test_no_provider_returns_none_records_nothing(self) -> None:
        tracker = CostTracker()
        orch = _bare_orchestrator(None, tracker)
        result = await orch._llm_enhance(Action(type="reply", payload={"content": "hi"}), _ctx())
        assert result is None
        assert tracker.get_summary()["total_requests"] == 0


# ---------------------------------------------------------------------------
# Tool-result path — _llm_enhance_tool_result
# ---------------------------------------------------------------------------


class TestToolResultEnhanceCost:
    @pytest.mark.asyncio
    async def test_records_cost_and_returns_tokens(self) -> None:
        tracker = CostTracker()
        orch = _bare_orchestrator(MockProvider(), tracker)
        text, tokens = await orch._llm_enhance_tool_result(
            "订单已发货", {"order_id": "ORD-1"}, _ctx()
        )
        assert text is not None
        assert tokens == 30
        assert tracker.get_summary()["total_tokens"] == 30

    @pytest.mark.asyncio
    async def test_no_provider_returns_none_zero(self) -> None:
        orch = _bare_orchestrator(None)
        text, tokens = await orch._llm_enhance_tool_result("x", None, _ctx())
        assert text is None
        assert tokens == 0


# ---------------------------------------------------------------------------
# End-to-end — token usage bubbles up to response.meta
# ---------------------------------------------------------------------------


class _ReplyStrategy:
    async def decide(self, intent, context, tools) -> Action:
        return Action(type="reply", payload={"content": "你好"})


class _FixedIntent:
    async def classify(self, message, context) -> Intent:
        return Intent(
            name="greeting", display_name="问候", confidence=1.0,
            source="rule", entities={},
        )


class _EmptyInjector:
    async def inject(self, intent, context):
        return []


class TestMetaExposesTokenUsage:
    @pytest.mark.asyncio
    async def test_response_meta_carries_real_token_usage(self) -> None:
        tracker = CostTracker()
        orch = DialogueOrchestrator(
            security_guard=SecurityGuard({}),
            context_manager=InMemoryContextManager(),
            intent_engine=_FixedIntent(),
            tool_injector=_EmptyInjector(),
            strategy=_ReplyStrategy(),
        )
        orch.set_provider(MockProvider())
        orch.set_cost_tracker(tracker)
        resp = await orch.handle_message(
            UserMessage(session_id="s1", content="你好", channel="web")
        )
        # token_usage survives the _core_handle meta merge (not overwritten),
        # alongside the routing facts.
        assert resp.meta.get("token_usage") == 30
        assert resp.meta.get("intent_name") == "greeting"
