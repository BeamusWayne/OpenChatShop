"""Regression tests for the re-audit orchestrator fixes (main-loop owned).

1. Confirmation must not read a verify/check request ("我要先确认一下金额") as
   consent — only genuine affirmations execute the irreversible write.
2. Human-handoff auto-assign must not strand THIS caller in HUMAN_MODE when a
   DIFFERENT (higher-priority) session is the one that actually got the agent.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from open_chat_shop.core.confirmation_resolver import ConfirmationResolver
from open_chat_shop.core.context import InMemoryContextManager
from open_chat_shop.core.handoff import (
    AgentStatus,
    HandoffQueue,
    HumanAgent,
    TransferRequest,
)
from open_chat_shop.core.intent import CascadeIntentEngine, RuleBasedMatcher
from open_chat_shop.core.orchestrator import DialogueOrchestrator
from open_chat_shop.core.security import SecurityGuard
from open_chat_shop.core.strategy import RuleBasedStrategy
from open_chat_shop.core.tool import ToolInjector
from open_chat_shop.core.types import (
    Action,
    AgentMessage,
    Message,
    SessionContext,
    SessionMode,
    UserMessage,
)


def _orchestrator() -> DialogueOrchestrator:
    return DialogueOrchestrator(
        security_guard=SecurityGuard({}),
        context_manager=InMemoryContextManager(),
        intent_engine=CascadeIntentEngine(RuleBasedMatcher()),
        tool_injector=ToolInjector(registry={}, routing_rules=[]),
        strategy=RuleBasedStrategy(),
    )


class TestConfirmVerifyHedge:
    @pytest.mark.parametrize(
        "text", ["确认一下金额", "我要先确认一下金额", "看一下", "核对一下订单", "确定一下"]
    )
    def test_verify_request_is_not_consent(self, text: str) -> None:
        # RED before the fix: the substring affirm match returned "affirm".
        assert ConfirmationResolver._detect_affirmation(text) is None

    @pytest.mark.parametrize("text", ["确认", "确定执行", "好的", "可以", "是的", "ok"])
    def test_genuine_consent_still_affirms(self, text: str) -> None:
        assert ConfirmationResolver._detect_affirmation(text) == "affirm"

    @pytest.mark.parametrize("text", ["取消", "不要", "算了"])
    def test_negation_still_denies(self, text: str) -> None:
        assert ConfirmationResolver._detect_affirmation(text) == "deny"


class TestHandoffAutoAssignSession:
    @pytest.mark.asyncio
    async def test_other_session_assigned_does_not_strand_this_caller(self) -> None:
        orch = _orchestrator()
        queue = HandoffQueue()
        queue.register_agent(
            HumanAgent(agent_id="a1", name="Alice", status=AgentStatus.ONLINE)
        )
        # Session A is already waiting -> it is queue[0] (highest priority).
        queue.enqueue(
            TransferRequest(request_id="trA", session_id="A", user_id="uA", reason="x")
        )
        orch.set_handoff_queue(queue)

        # Session B requests transfer. The single agent goes to A (queue[0]),
        # NOT B — so B must remain waiting, never falsely connected.
        ctx_b = SessionContext(session_id="B", user_id="uB", channel="web")
        await orch._execute_action(
            Action(type="transfer", payload={"reason": "handoff"}), ctx_b, []
        )

        assert ctx_b.mode != SessionMode.HUMAN_MODE  # RED before fix: was HUMAN_MODE
        assert ctx_b.human_agent_id is None
        assert queue.get_active_transfer("A") is not None  # A actually got the agent
        assert queue.get_active_transfer("B") is None


class TestRecordTurnTimestamps:
    """The DB backend reconstructs history order from created_at, so _record_turn
    must assign STRICTLY-INCREASING timestamps (the default Message factory ties
    the back-to-back user+assistant pair, scrambling DB reload order into the LLM
    prompt — audit CRITICAL). The tie is timing-dependent, so force the scenario
    deterministically by seeding a future-stamped turn: the new pair must land
    strictly after it (without the fix it uses now() < the seed -> reliably RED).
    """

    def test_new_turn_anchored_strictly_after_existing_history(self) -> None:
        ctx = SessionContext(session_id="s", user_id="u", channel="web")
        future = datetime.now(UTC) + timedelta(hours=1)
        ctx.history.append(Message(role="assistant", content="seed", timestamp=future))
        DialogueOrchestrator._record_turn(
            ctx,
            UserMessage(session_id="s", content="hi", channel="web"),
            AgentMessage(message_type="text", payload={}, text_fallback="hello"),
        )
        ts = [m.timestamp for m in ctx.history]
        assert all(ts[i] < ts[i + 1] for i in range(len(ts) - 1)), ts
        assert ts[1] > future


class TestSlotFillParamNames:
    """Every required tool param (besides the regex-extracted order_id) must have
    a slot-fill prompt, or it is a conversational dead-end. The audit found
    modify_address required 'address' but the slot machinery only knew
    'new_address', so the slot was never fillable."""

    def test_required_tool_params_have_slot_fill_prompts(self) -> None:
        from open_chat_shop.core.strategy import RuleBasedStrategy
        from open_chat_shop.tools.builtin.modify_address import ModifyAddressTool

        required = set(ModifyAddressTool.params_schema["required"])
        prompts = set(RuleBasedStrategy._MISSING_PARAM_PROMPTS)
        missing = required - prompts - {"order_id"}
        assert not missing, f"required params with no slot-fill prompt: {missing}"
