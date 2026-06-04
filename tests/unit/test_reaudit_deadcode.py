"""Re-audit cluster: deadcode.

Two surfaces were flagged as dead in a re-audit:

1. The Scenario FSM subsystem (``core/scenario.py`` + ``core/scenarios/*``).
   The flag's premise — "never wired into the runtime orchestrator path" — is
   FALSE: ``main.py`` (the production composition root) instantiates
   ``RefundScenarioFSM`` / ``ComplaintScenarioFSM`` / ``OrderInquiryScenarioFSM``
   and registers them via ``DialogueOrchestrator.set_scenarios``; the
   orchestrator's ``switch_scenario`` action then drives them through the FSM
   contract (``get_initial_state``). These tests pin that real
   orchestrator<->FSM seam so the subsystem cannot be mistaken for dead code
   and deleted.

2. ``provider.CascadeStrategy`` — the concrete realization of the
   ``LLMProvider`` ABC's documented "cascade strategy and capability
   degradation" contract. It is a deliberate extension point (multi-provider
   fallback) kept on purpose; ``_build_provider`` returns a single provider
   today, but the capability-degradation contract is pinned here so it cannot
   silently rot.

Each test fails (or errors at import time) if the corresponding surface is
removed, which is exactly the regression we want to prevent.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from open_chat_shop.core.orchestrator import DialogueOrchestrator
from open_chat_shop.core.provider import (
    CascadeStrategy,
    FailingProvider,
    MockProvider,
)
from open_chat_shop.core.scenario import RefundScenarioFSM, ScenarioFSM
from open_chat_shop.core.scenarios.complaint import ComplaintScenarioFSM
from open_chat_shop.core.scenarios.order_inquiry import OrderInquiryScenarioFSM
from open_chat_shop.core.types import (
    Action,
    Message,
    ProviderCapabilities,
    SessionContext,
    ToolDefinition,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _bare_orchestrator() -> DialogueOrchestrator:
    """An orchestrator whose deps are all None.

    The ``switch_scenario`` action path does not touch security / context /
    intent / tools, and ``_llm_enhance`` short-circuits to ``None`` when no
    provider is set — so the deterministic FSM branch runs and exercises the
    real ScenarioFSM contract with no mocks.
    """
    return DialogueOrchestrator(None, None, None, None, None)


def _session() -> SessionContext:
    return SessionContext(session_id="s1", user_id="u1", channel="web")


# ---------------------------------------------------------------------------
# Finding 1 — Scenario FSM subsystem is LIVE (wired into orchestrator path)
# ---------------------------------------------------------------------------


class TestScenarioFsmWiredIntoOrchestrator:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_switch_scenario_drives_real_fsm_contract(self) -> None:
        """REAL-INTERACTION test of the orchestrator<->ScenarioFSM seam.

        Registers genuine FSM instances (no mocks) and routes a
        ``switch_scenario`` action through ``_execute_action``. The orchestrator
        must call ``scenario.get_initial_state()`` and stamp it onto the
        context. If the Scenario FSM subsystem were deleted as "dead code",
        ``set_scenarios`` would have nothing real to register and this contract
        would break — so this test fails the deletion.
        """
        orch = _bare_orchestrator()
        orch.set_scenarios(
            {
                "refund": RefundScenarioFSM(),
                "complaint": ComplaintScenarioFSM(),
                "order_inquiry": OrderInquiryScenarioFSM(),
            }
        )

        for scenario_name, expected_initial in (
            ("refund", "initiated"),
            ("complaint", "idle"),
            ("order_inquiry", "idle"),
        ):
            ctx = _session()
            action = Action(type="switch_scenario", payload={"scenario": scenario_name})

            msg = await orch._execute_action(action, ctx, tools=[])

            # The FSM's get_initial_state() result is now the live fsm_state.
            assert ctx.fsm_state == expected_initial
            assert ctx.current_scenario == scenario_name
            # The deterministic (no-LLM) branch returns the entry-prompt fallback.
            assert scenario_name in msg.text_fallback

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_switch_scenario_initial_state_matches_fsm_directly(self) -> None:
        """The state the orchestrator stamps equals the FSM's own contract.

        Guards against a future refactor that hard-codes initial states in the
        orchestrator instead of delegating to ``get_initial_state`` — that would
        silently re-orphan the FSM subsystem.
        """
        fsm = RefundScenarioFSM()
        orch = _bare_orchestrator()
        orch.set_scenarios({"refund": fsm})

        ctx = _session()
        await orch._execute_action(
            Action(type="switch_scenario", payload={"scenario": "refund"}),
            ctx,
            tools=[],
        )

        assert ctx.fsm_state == fsm.get_initial_state()

    @pytest.mark.unit
    def test_concrete_scenarios_satisfy_abc_contract(self) -> None:
        """All shipped FSMs are real ScenarioFSM subclasses with a valid initial
        state inside their declared ``states`` set."""
        for fsm in (
            RefundScenarioFSM(),
            ComplaintScenarioFSM(),
            OrderInquiryScenarioFSM(),
        ):
            assert isinstance(fsm, ScenarioFSM)
            assert fsm.get_initial_state() in fsm.states
            # name is what main.py keys set_scenarios by.
            assert isinstance(fsm.name, str) and fsm.name

    @pytest.mark.unit
    def test_main_composition_root_wires_scenario_fsms(self) -> None:
        """The production entry point actually imports and registers the FSMs.

        This directly refutes the audit premise ("never wired into the runtime
        orchestrator path"). We assert against the real ``main.py`` source text
        (rather than importing it, which would pull heavy runtime deps) so the
        test fails loudly if the wiring is removed.
        """
        main_src = (_REPO_ROOT / "main.py").read_text(encoding="utf-8")
        assert "set_scenarios(" in main_src
        for symbol in (
            "RefundScenarioFSM",
            "ComplaintScenarioFSM",
            "OrderInquiryScenarioFSM",
        ):
            assert symbol in main_src, f"{symbol} no longer wired in main.py"


# ---------------------------------------------------------------------------
# Finding 2 — CascadeStrategy is a documented, intentional contract surface
# ---------------------------------------------------------------------------


class _NoToolProvider(MockProvider):
    """Provider that does not support tool calling."""

    name = "no_tool"

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            tool_calling=False,
            streaming=True,
            vision=False,
            max_context_tokens=4096,
            supported_locales=["en"],
        )


class TestCascadeStrategyContract:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_capability_degradation_drops_tools_for_nontool_provider(self) -> None:
        """Pins the documented degradation: tool_calling -> text (tools dropped).

        A provider whose ``get_capabilities().tool_calling`` is False must be
        called with ``tools=None``. This is the core contract the ABC docstring
        promises and the reason CascadeStrategy is kept as an extension point.
        """
        provider = _NoToolProvider()
        cascade = CascadeStrategy([provider])

        tools = [
            ToolDefinition(
                name="t", description="d", parameters={"type": "object", "properties": {}}
            )
        ]
        _response, name = await cascade.chat(
            [Message(role="user", content="hi")], tools=tools
        )

        assert name == "no_tool"
        # MockProvider.call_log records the tools_count it actually received.
        assert provider.call_log[-1]["tools_count"] == 0

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_cascade_falls_through_to_next_provider(self) -> None:
        """First provider failing must cascade to the next and report which one
        served the response."""
        cascade = CascadeStrategy(
            [FailingProvider(), MockProvider(default_response="fallback")]
        )

        response, name = await cascade.chat([Message(role="user", content="hi")])

        assert response.content == "fallback"
        assert name == "mock"
