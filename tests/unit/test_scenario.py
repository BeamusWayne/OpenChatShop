"""Unit tests for the Scenario FSM framework (feat-010)."""
from __future__ import annotations

from datetime import datetime

import pytest

from open_chat_shop.core.scenario import RefundScenarioFSM, ScenarioFSM
from open_chat_shop.core.types import SessionContext, Transition


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_context(**overrides: object) -> SessionContext:
    """Create a minimal valid SessionContext for testing."""
    defaults: dict[str, object] = dict(
        session_id="test-123",
        user_id="user-1",
        channel="web",
        history=[],
        summary=None,
        slots={},
        fsm_state="initiated",
        current_scenario=None,
        token_usage=0,
        user_role="customer",
    )
    defaults.update(overrides)
    return SessionContext(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# ABC interface tests
# ---------------------------------------------------------------------------


class TestScenarioFSMAbstract:
    """ScenarioFSM cannot be instantiated directly."""

    @pytest.mark.unit
    def test_cannot_instantiate_abc(self) -> None:
        with pytest.raises(TypeError):
            ScenarioFSM()  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# RefundScenarioFSM – basic properties
# ---------------------------------------------------------------------------


class TestRefundScenarioProperties:
    @pytest.mark.unit
    def test_name(self) -> None:
        assert RefundScenarioFSM().name == "refund"

    @pytest.mark.unit
    def test_states(self) -> None:
        expected = ["initiated", "confirmed", "processing", "completed", "cancelled"]
        assert RefundScenarioFSM().states == expected

    @pytest.mark.unit
    def test_initial_state(self) -> None:
        assert RefundScenarioFSM().get_initial_state() == "initiated"

    @pytest.mark.unit
    def test_timeout(self) -> None:
        assert RefundScenarioFSM().timeout_seconds == 300


# ---------------------------------------------------------------------------
# Allowed transitions
# ---------------------------------------------------------------------------


class TestAllowedTransitions:
    """Verify get_allowed_transitions returns correct transitions per state."""

    @pytest.fixture()
    def fsm(self) -> RefundScenarioFSM:
        return RefundScenarioFSM()

    @pytest.mark.unit
    def test_from_initiated(self, fsm: RefundScenarioFSM) -> None:
        transitions = fsm.get_allowed_transitions("initiated")
        triggers = {t.trigger for t in transitions}
        assert triggers == {"confirm", "cancel"}

    @pytest.mark.unit
    def test_from_confirmed(self, fsm: RefundScenarioFSM) -> None:
        transitions = fsm.get_allowed_transitions("confirmed")
        triggers = {t.trigger for t in transitions}
        assert triggers == {"process", "cancel"}

    @pytest.mark.unit
    def test_from_processing(self, fsm: RefundScenarioFSM) -> None:
        transitions = fsm.get_allowed_transitions("processing")
        triggers = {t.trigger for t in transitions}
        assert triggers == {"complete", "cancel"}

    @pytest.mark.unit
    def test_from_completed_empty(self, fsm: RefundScenarioFSM) -> None:
        transitions = fsm.get_allowed_transitions("completed")
        assert transitions == []

    @pytest.mark.unit
    def test_from_cancelled_empty(self, fsm: RefundScenarioFSM) -> None:
        transitions = fsm.get_allowed_transitions("cancelled")
        assert transitions == []


# ---------------------------------------------------------------------------
# can_transition
# ---------------------------------------------------------------------------


class TestCanTransition:
    @pytest.fixture()
    def fsm(self) -> RefundScenarioFSM:
        return RefundScenarioFSM()

    @pytest.mark.unit
    def test_valid_confirm(self, fsm: RefundScenarioFSM) -> None:
        ctx = _make_context(fsm_state="initiated")
        assert fsm.can_transition("initiated", "confirm", ctx) is True

    @pytest.mark.unit
    def test_valid_cancel_from_initiated(self, fsm: RefundScenarioFSM) -> None:
        ctx = _make_context(fsm_state="initiated")
        assert fsm.can_transition("initiated", "cancel", ctx) is True

    @pytest.mark.unit
    def test_invalid_complete_from_initiated(self, fsm: RefundScenarioFSM) -> None:
        ctx = _make_context(fsm_state="initiated")
        assert fsm.can_transition("initiated", "complete", ctx) is False

    @pytest.mark.unit
    def test_invalid_confirm_from_processing(self, fsm: RefundScenarioFSM) -> None:
        ctx = _make_context(fsm_state="processing")
        assert fsm.can_transition("processing", "confirm", ctx) is False

    @pytest.mark.unit
    def test_no_transitions_from_terminal_state(self, fsm: RefundScenarioFSM) -> None:
        ctx = _make_context(fsm_state="completed")
        assert fsm.can_transition("completed", "confirm", ctx) is False
        assert fsm.can_transition("completed", "cancel", ctx) is False


# ---------------------------------------------------------------------------
# execute_transition
# ---------------------------------------------------------------------------


class TestExecuteTransition:
    @pytest.fixture()
    def fsm(self) -> RefundScenarioFSM:
        return RefundScenarioFSM()

    @pytest.mark.unit
    async def test_updates_fsm_state(self, fsm: RefundScenarioFSM) -> None:
        ctx = _make_context(fsm_state="initiated")
        new_ctx = await fsm.execute_transition("initiated", "confirm", ctx)
        assert new_ctx.fsm_state == "confirmed"

    @pytest.mark.unit
    async def test_sets_current_scenario(self, fsm: RefundScenarioFSM) -> None:
        ctx = _make_context(fsm_state="initiated", current_scenario=None)
        new_ctx = await fsm.execute_transition("initiated", "confirm", ctx)
        assert new_ctx.current_scenario == "refund"

    @pytest.mark.unit
    async def test_does_not_mutate_original(self, fsm: RefundScenarioFSM) -> None:
        ctx = _make_context(fsm_state="initiated", current_scenario=None)
        original_state = ctx.fsm_state
        original_scenario = ctx.current_scenario
        _ = await fsm.execute_transition("initiated", "confirm", ctx)
        assert ctx.fsm_state == original_state
        assert ctx.current_scenario == original_scenario

    @pytest.mark.unit
    async def test_raises_on_invalid_transition(self, fsm: RefundScenarioFSM) -> None:
        ctx = _make_context(fsm_state="initiated")
        with pytest.raises(ValueError, match="not allowed"):
            await fsm.execute_transition("initiated", "complete", ctx)

    @pytest.mark.unit
    async def test_preserves_other_fields(self, fsm: RefundScenarioFSM) -> None:
        ctx = _make_context(
            fsm_state="initiated",
            session_id="ses-abc",
            user_id="u-42",
            channel="miniapp",
            token_usage=150,
        )
        new_ctx = await fsm.execute_transition("initiated", "confirm", ctx)
        assert new_ctx.session_id == "ses-abc"
        assert new_ctx.user_id == "u-42"
        assert new_ctx.channel == "miniapp"
        assert new_ctx.token_usage == 150


# ---------------------------------------------------------------------------
# Full lifecycle
# ---------------------------------------------------------------------------


class TestFullRefundLifecycle:
    @pytest.mark.unit
    async def test_happy_path(self) -> None:
        """initiated -> confirmed -> processing -> completed"""
        fsm = RefundScenarioFSM()
        ctx = _make_context(fsm_state="initiated")

        ctx = await fsm.execute_transition("initiated", "confirm", ctx)
        assert ctx.fsm_state == "confirmed"

        ctx = await fsm.execute_transition("confirmed", "process", ctx)
        assert ctx.fsm_state == "processing"

        ctx = await fsm.execute_transition("processing", "complete", ctx)
        assert ctx.fsm_state == "completed"

    @pytest.mark.unit
    async def test_cancel_from_initiated(self) -> None:
        fsm = RefundScenarioFSM()
        ctx = _make_context(fsm_state="initiated")
        ctx = await fsm.execute_transition("initiated", "cancel", ctx)
        assert ctx.fsm_state == "cancelled"

    @pytest.mark.unit
    async def test_cancel_from_confirmed(self) -> None:
        fsm = RefundScenarioFSM()
        ctx = _make_context(fsm_state="initiated")
        ctx = await fsm.execute_transition("initiated", "confirm", ctx)
        ctx = await fsm.execute_transition("confirmed", "cancel", ctx)
        assert ctx.fsm_state == "cancelled"

    @pytest.mark.unit
    async def test_cancel_from_processing(self) -> None:
        fsm = RefundScenarioFSM()
        ctx = _make_context(fsm_state="initiated")
        ctx = await fsm.execute_transition("initiated", "confirm", ctx)
        ctx = await fsm.execute_transition("confirmed", "process", ctx)
        ctx = await fsm.execute_transition("processing", "cancel", ctx)
        assert ctx.fsm_state == "cancelled"


# ---------------------------------------------------------------------------
# Guard function
# ---------------------------------------------------------------------------


class TestGuardFunction:
    @pytest.mark.unit
    async def test_guard_blocks_transition(self) -> None:
        """A guard returning False should prevent the transition."""

        def _deny_all(context: SessionContext) -> bool:
            return False

        fsm = RefundScenarioFSM()
        # Manually inject a guarded transition
        guarded = Transition(
            from_state="initiated",
            to_state="confirmed",
            trigger="confirm",
            guard=_deny_all,
        )
        fsm.transitions = [guarded]

        ctx = _make_context(fsm_state="initiated")
        assert fsm.can_transition("initiated", "confirm", ctx) is False

        with pytest.raises(ValueError, match="not allowed"):
            await fsm.execute_transition("initiated", "confirm", ctx)

    @pytest.mark.unit
    async def test_guard_allows_transition(self) -> None:
        """A guard returning True should allow the transition."""

        def _allow_all(context: SessionContext) -> bool:
            return True

        fsm = RefundScenarioFSM()
        guarded = Transition(
            from_state="initiated",
            to_state="confirmed",
            trigger="confirm",
            guard=_allow_all,
        )
        fsm.transitions = [guarded]

        ctx = _make_context(fsm_state="initiated")
        assert fsm.can_transition("initiated", "confirm", ctx) is True
        new_ctx = await fsm.execute_transition("initiated", "confirm", ctx)
        assert new_ctx.fsm_state == "confirmed"
