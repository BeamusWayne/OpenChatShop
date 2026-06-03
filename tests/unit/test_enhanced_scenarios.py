"""Tests for enhanced scenario FSMs — OrderInquiry and Complaint."""
from __future__ import annotations

import pytest

from open_chat_shop.core.scenarios.complaint import ComplaintScenarioFSM
from open_chat_shop.core.scenarios.order_inquiry import OrderInquiryScenarioFSM
from open_chat_shop.core.types import SessionContext


def _ctx(**overrides) -> SessionContext:
    defaults = dict(session_id="s1", user_id="u1", channel="web")
    defaults.update(overrides)
    return SessionContext(**defaults)


# ===========================================================================
# OrderInquiryScenarioFSM
# ===========================================================================


class TestOrderInquiryFSM:
    @pytest.mark.unit
    def test_initial_state(self):
        fsm = OrderInquiryScenarioFSM()
        assert fsm.get_initial_state() == "idle"

    @pytest.mark.unit
    def test_states_defined(self):
        fsm = OrderInquiryScenarioFSM()
        assert "idle" in fsm.states
        assert "querying" in fsm.states
        assert "located" in fsm.states
        assert "displaying" in fsm.states
        assert "follow_up" in fsm.states
        assert "completed" in fsm.states
        assert "cancelled" in fsm.states

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_happy_path(self):
        """idle -> querying -> located -> displaying -> completed"""
        fsm = OrderInquiryScenarioFSM()
        ctx = _ctx(slots={"order_id": "ORD-123"})

        # idle -> querying
        assert fsm.can_transition("idle", "start_query", ctx)
        ctx = await fsm.execute_transition("idle", "start_query", ctx)
        assert ctx.fsm_state == "querying"

        # querying -> located (needs order_id in slots)
        assert fsm.can_transition("querying", "order_found", ctx)
        ctx = await fsm.execute_transition("querying", "order_found", ctx)
        assert ctx.fsm_state == "located"

        # located -> displaying
        ctx = await fsm.execute_transition("located", "display", ctx)
        assert ctx.fsm_state == "displaying"

        # displaying -> completed
        ctx = await fsm.execute_transition("displaying", "resolve", ctx)
        assert ctx.fsm_state == "completed"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_follow_up_path(self):
        """displaying -> follow_up -> completed"""
        fsm = OrderInquiryScenarioFSM()
        ctx = _ctx(fsm_state="displaying", slots={"order_id": "ORD-1"})

        ctx = await fsm.execute_transition("displaying", "ask_followup", ctx)
        assert ctx.fsm_state == "follow_up"

        ctx = await fsm.execute_transition("follow_up", "resolve", ctx)
        assert ctx.fsm_state == "completed"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_order_not_found(self):
        """querying -> cancelled when not found"""
        fsm = OrderInquiryScenarioFSM()
        ctx = _ctx(fsm_state="querying")

        ctx = await fsm.execute_transition("querying", "not_found", ctx)
        assert ctx.fsm_state == "cancelled"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_guard_requires_order_id(self):
        """order_found transition blocked without order_id in slots"""
        fsm = OrderInquiryScenarioFSM()
        ctx = _ctx(fsm_state="querying", slots={})  # no order_id

        assert not fsm.can_transition("querying", "order_found", ctx)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_guard_passes_with_order_id(self):
        fsm = OrderInquiryScenarioFSM()
        ctx = _ctx(fsm_state="querying", slots={"order_id": "ORD-999"})

        assert fsm.can_transition("querying", "order_found", ctx)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_cancel_from_any_state(self):
        """Cancel works from idle, querying, displaying, follow_up, located"""
        fsm = OrderInquiryScenarioFSM()
        ctx = _ctx()

        for state in ["idle", "displaying", "follow_up", "located"]:
            assert fsm.can_transition(state, "cancel", ctx), f"cancel from {state}"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_invalid_transition_raises(self):
        fsm = OrderInquiryScenarioFSM()
        ctx = _ctx()

        with pytest.raises(ValueError, match="not allowed"):
            await fsm.execute_transition("idle", "display", ctx)

    @pytest.mark.unit
    def test_timeout_configured(self):
        fsm = OrderInquiryScenarioFSM()
        assert fsm.timeout_seconds == 180


# ===========================================================================
# ComplaintScenarioFSM
# ===========================================================================


class TestComplaintFSM:
    @pytest.mark.unit
    def test_initial_state(self):
        fsm = ComplaintScenarioFSM()
        assert fsm.get_initial_state() == "idle"

    @pytest.mark.unit
    def test_states_defined(self):
        fsm = ComplaintScenarioFSM()
        expected = {"idle", "received", "classified", "investigating",
                    "resolving", "resolved", "escalated"}
        assert set(fsm.states) == expected

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_happy_path(self):
        """idle -> received -> classified -> investigating -> resolving -> resolved"""
        fsm = ComplaintScenarioFSM()
        ctx = _ctx(slots={"complaint_category": "quality"})

        ctx = await fsm.execute_transition("idle", "submit", ctx)
        assert ctx.fsm_state == "received"

        ctx = await fsm.execute_transition("received", "classify", ctx)
        assert ctx.fsm_state == "classified"

        ctx = await fsm.execute_transition("classified", "investigate", ctx)
        assert ctx.fsm_state == "investigating"

        ctx = await fsm.execute_transition("investigating", "resolve_start", ctx)
        assert ctx.fsm_state == "resolving"

        ctx = await fsm.execute_transition("resolving", "complete", ctx)
        assert ctx.fsm_state == "resolved"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_escalation_from_investigating(self):
        fsm = ComplaintScenarioFSM()
        ctx = _ctx(fsm_state="investigating")

        ctx = await fsm.execute_transition("investigating", "escalate", ctx)
        assert ctx.fsm_state == "escalated"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_escalation_from_resolving(self):
        fsm = ComplaintScenarioFSM()
        ctx = _ctx(fsm_state="resolving")

        ctx = await fsm.execute_transition("resolving", "escalate", ctx)
        assert ctx.fsm_state == "escalated"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_escalation_from_classified(self):
        fsm = ComplaintScenarioFSM()
        ctx = _ctx(fsm_state="classified")

        ctx = await fsm.execute_transition("classified", "escalate", ctx)
        assert ctx.fsm_state == "escalated"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_guard_requires_valid_category(self):
        fsm = ComplaintScenarioFSM()
        for cat in ["quality", "service", "logistics", "other"]:
            ctx = _ctx(fsm_state="received", slots={"complaint_category": cat})
            assert fsm.can_transition("received", "classify", ctx), f"category={cat}"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_guard_blocks_invalid_category(self):
        fsm = ComplaintScenarioFSM()
        ctx = _ctx(fsm_state="received", slots={"complaint_category": "invalid"})
        assert not fsm.can_transition("received", "classify", ctx)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_guard_blocks_empty_category(self):
        fsm = ComplaintScenarioFSM()
        ctx = _ctx(fsm_state="received", slots={})
        assert not fsm.can_transition("received", "classify", ctx)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_invalid_transition_raises(self):
        fsm = ComplaintScenarioFSM()
        ctx = _ctx(fsm_state="idle")

        with pytest.raises(ValueError, match="not allowed"):
            await fsm.execute_transition("idle", "investigate", ctx)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_no_transition_from_resolved(self):
        """resolved is a terminal state — no transitions out."""
        fsm = ComplaintScenarioFSM()
        ctx = _ctx()
        transitions = fsm.get_allowed_transitions("resolved")
        assert transitions == []

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_no_transition_from_escalated(self):
        """escalated is a terminal state."""
        fsm = ComplaintScenarioFSM()
        ctx = _ctx()
        transitions = fsm.get_allowed_transitions("escalated")
        assert transitions == []

    @pytest.mark.unit
    def test_timeout_configured(self):
        fsm = ComplaintScenarioFSM()
        assert fsm.timeout_seconds == 600
