"""Regression tests for the high-risk confirmation loop (audit HIGH-9).

Before this fix the strategy emitted a ``confirm`` action with a
``pending_action`` payload, but the orchestrator only persisted the
``clarify`` branch's ``_pending_action``. The confirmation was a dead end:
a user replying "确认" was re-classified from scratch, so the gated write
either never executed or was re-recognised and executed *without* the gate.

This pins the wired loop:
  - a ``confirm`` action persists ``_pending_confirmation`` on the context;
  - an affirmative reply executes the gated tool with the stored params;
  - a declining reply discards it (tool never runs);
  - an unrelated reply discards it and is processed as a new request
    (fail-safe: non-affirmative never executes the irreversible write).
"""
from __future__ import annotations

import pytest

from open_chat_shop.core.context import InMemoryContextManager
from open_chat_shop.core.intent import (
    CascadeIntentEngine,
    IntentInfo,
    RuleBasedMatcher,
)
from open_chat_shop.core.orchestrator import DialogueOrchestrator
from open_chat_shop.core.security import SecurityGuard
from open_chat_shop.core.strategy import RuleBasedStrategy
from open_chat_shop.core.tool import BaseTool, ToolInjector
from open_chat_shop.core.types import (
    RoutingRule,
    SessionContext,
    ToolPermission,
    ToolResult,
    UserMessage,
)


class _DangerTool(BaseTool):
    """A no-arg high-risk tool that requires confirmation."""

    def __init__(self) -> None:
        self.name = "danger_op"
        self.description = "高风险操作"
        self.category = "test"
        self.params_schema = {"type": "object", "properties": {}}
        self.permissions = ToolPermission(
            required_roles=["*"], idempotent=False, requires_confirmation=True
        )
        self.executed = False

    async def execute(self, params: dict, context: SessionContext) -> ToolResult:
        self.executed = True
        return ToolResult(success=True, data={"done": True})


def _build(tool: BaseTool) -> DialogueOrchestrator:
    security = SecurityGuard(
        {"rbac": {"roles": [{"name": "customer", "tools": [tool.name]}]}}
    )
    matcher = RuleBasedMatcher()
    matcher.add_rule("danger_op", r"危险|删除|danger")
    matcher.add_rule("query_order", r"查询.*订单|查订单|订单")
    engine = CascadeIntentEngine(matcher)
    engine.register_intent(IntentInfo("danger_op", "危险操作", "高风险操作", 5))
    engine.register_intent(IntentInfo("query_order", "查询订单", "查询订单", 5))
    injector = ToolInjector(
        {tool.name: tool},
        [RoutingRule(intent_patterns=["danger_op"], tools=[tool.name], priority=10)],
    )
    return DialogueOrchestrator(
        security, InMemoryContextManager(), engine, injector, RuleBasedStrategy()
    )


def _msg(content: str, session_id: str = "s1") -> UserMessage:
    return UserMessage(session_id=session_id, content=content, channel="web")


# ---------------------------------------------------------------------------
# Affirmation detection (rule-based, deterministic)
# ---------------------------------------------------------------------------


class TestDetectAffirmation:
    @pytest.mark.parametrize(
        "text",
        ["确认", "是", "是的", "对", "好的", "可以", "嗯", "确定执行", "ok", "yes"],
    )
    def test_affirmative(self, text: str) -> None:
        assert DialogueOrchestrator._detect_affirmation(text) == "affirm"

    @pytest.mark.parametrize(
        "text",
        ["取消", "不", "不是", "算了", "不用", "不确定", "no", "cancel"],
    )
    def test_negative(self, text: str) -> None:
        assert DialogueOrchestrator._detect_affirmation(text) == "deny"

    @pytest.mark.parametrize("text", ["查询订单", "你好", "帮我看看商品"])
    def test_ambiguous_returns_none(self, text: str) -> None:
        assert DialogueOrchestrator._detect_affirmation(text) is None


# ---------------------------------------------------------------------------
# End-to-end confirmation loop
# ---------------------------------------------------------------------------


class TestConfirmLoop:
    @pytest.mark.asyncio
    async def test_first_turn_persists_pending_confirmation(self) -> None:
        tool = _DangerTool()
        orch = _build(tool)
        resp = await orch.handle_message(_msg("执行删除危险操作"))
        assert resp.message_type == "confirm"
        assert resp.requires_confirmation is True
        assert tool.executed is False
        # The confirmation is persisted for the next turn.
        ctx = orch._context_manager.get("s1")
        assert ctx is not None
        assert ctx.slots.get("_pending_confirmation") is not None

    @pytest.mark.asyncio
    async def test_affirmative_reply_executes_gated_tool(self) -> None:
        tool = _DangerTool()
        orch = _build(tool)
        await orch.handle_message(_msg("执行删除危险操作"))
        resp = await orch.handle_message(_msg("确认"))
        assert tool.executed is True
        assert resp.message_type != "confirm"
        # One-shot: the pending confirmation is cleared after use.
        ctx = orch._context_manager.get("s1")
        assert ctx.slots.get("_pending_confirmation") is None

    @pytest.mark.asyncio
    async def test_declining_reply_discards_without_executing(self) -> None:
        tool = _DangerTool()
        orch = _build(tool)
        await orch.handle_message(_msg("执行删除危险操作"))
        resp = await orch.handle_message(_msg("取消"))
        assert tool.executed is False
        assert "取消" in resp.text_fallback
        ctx = orch._context_manager.get("s1")
        assert ctx.slots.get("_pending_confirmation") is None

    @pytest.mark.asyncio
    async def test_topic_switch_discards_and_reclassifies(self) -> None:
        tool = _DangerTool()
        orch = _build(tool)
        await orch.handle_message(_msg("执行删除危险操作"))
        # An unrelated request must NOT execute the gated tool.
        resp = await orch.handle_message(_msg("查询订单"))
        assert tool.executed is False
        ctx = orch._context_manager.get("s1")
        assert ctx.slots.get("_pending_confirmation") is None
        assert resp.message_type != "confirm"
