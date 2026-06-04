
"""Audit regression tests for cluster CORE1 (orchestrator identity + safety).

Each test here FAILS against the pre-remediation orchestrator and PASSES after
the fix. They exercise the *real* app -> orchestrator -> context -> tool path
(not the tool in isolation), which is exactly where the prior fixes were silently
dropped.
"""
from __future__ import annotations

from typing import ClassVar

import pytest

from open_chat_shop.core.confirmation_resolver import ConfirmationResolver
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
    AgentMessage,
    Message,
    RoutingRule,
    SessionContext,
    ToolPermission,
    ToolResult,
    UserMessage,
)
from open_chat_shop.tools.builtin.query_order import QueryOrderTool

# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _EchoEntityTool(BaseTool):
    """Returns the order_id it saw plus the user_id the context carried.

    Used to prove the verified identity actually reaches the tool layer via
    ``context.user_id`` (not just the HTTP boundary).
    """

    name = "query_order"
    description = "查询订单"
    category = "order"
    params_schema: ClassVar[dict] = {
        "type": "object",
        "properties": {"order_id": {"type": "string"}},
        "required": ["order_id"],
    }
    permissions = ToolPermission(required_roles=["customer"])

    async def execute(self, params, context):  # type: ignore[no-untyped-def]
        return ToolResult(
            success=True,
            data={
                "order_id": params.get("order_id", ""),
                "seen_user_id": context.user_id,
            },
        )


def _build_orchestrator(query_tool: BaseTool) -> DialogueOrchestrator:
    security = SecurityGuard(
        {
            "rbac": {
                "roles": [
                    {"name": "customer", "tools": ["query_order"]},
                    {"name": "admin", "tools": ["*"]},
                ]
            }
        }
    )
    context_mgr = InMemoryContextManager()

    matcher = RuleBasedMatcher()
    matcher.add_rule("query_order", r"订单|order|ORD-")
    engine = CascadeIntentEngine(matcher)
    engine.register_intent(
        IntentInfo(
            name="query_order",
            display_name="查询订单",
            description="查询订单状态",
            sample_count=10,
        )
    )

    injector = ToolInjector(
        {"query_order": query_tool},
        [RoutingRule(intent_patterns=["query_order"], tools=["query_order"], priority=10)],
    )
    return DialogueOrchestrator(
        security, context_mgr, engine, injector, RuleBasedStrategy()
    )


# ---------------------------------------------------------------------------
# CRITICAL — IDOR on the wired path: verified identity must reach the tool
# ---------------------------------------------------------------------------


class TestIdentityReachesToolLayer:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_message_user_id_is_propagated_to_context(self) -> None:
        """The JWT-bound message.user_id must arrive at context.user_id.

        Before the fix the orchestrator loaded a fresh context with
        user_id=None and never copied message.user_id, so the tool saw None.
        """
        orch = _build_orchestrator(_EchoEntityTool())
        msg = UserMessage(
            session_id="idor-s1",
            content="查询订单 ORD-001",
            channel="web",
            user_id="user-001",
        )
        resp = await orch.handle_message(msg)
        # The tool echoed the user_id it actually saw on the context.
        assert "user-001" in resp.text_fallback

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_foreign_order_is_not_found_end_to_end(self) -> None:
        """Full path with the REAL QueryOrderTool: attacker cannot read a
        non-owned order. ORD-001 is owned by user-001; user-999 must get
        'not found', proving get_for_user received the real identity."""
        orch = _build_orchestrator(QueryOrderTool())
        msg = UserMessage(
            session_id="idor-s2",
            content="查询订单 ORD-001",
            channel="web",
            user_id="user-999",  # owns no seeded order
        )
        resp = await orch.handle_message(msg)
        assert "ORD-001" in resp.text_fallback  # surfaced as not-found
        assert "未找到" in resp.text_fallback

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_owner_succeeds_end_to_end(self) -> None:
        """Sanity: the real owner still reads their own order (no false deny)."""
        orch = _build_orchestrator(QueryOrderTool())
        msg = UserMessage(
            session_id="idor-s3",
            content="查询订单 ORD-001",
            channel="web",
            user_id="user-001",
        )
        resp = await orch.handle_message(msg)
        # Owner gets real order content, not a not-found.
        assert "未找到" not in resp.text_fallback

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_anonymous_path_still_works(self) -> None:
        """When auth is disabled (user_id=None) ownership is not enforced, so
        the local/dev demo keeps working — the fix must not break this."""
        orch = _build_orchestrator(QueryOrderTool())
        msg = UserMessage(
            session_id="idor-s4",
            content="查询订单 ORD-001",
            channel="web",
            user_id=None,
        )
        resp = await orch.handle_message(msg)
        assert "未找到" not in resp.text_fallback

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_identity_takeover_is_refused(self) -> None:
        """A session already bound to user-001 must not be hijacked by a
        second message claiming user-999 — refuse rather than rebind."""
        ctx = InMemoryContextManager()
        # Pre-bind the session to user-001.
        loaded = await ctx.load("idor-s5", channel="web")
        loaded.user_id = "user-001"
        await ctx.save(loaded, AgentMessage(message_type="text", payload={}, text_fallback=""))

        orch = _build_orchestrator(QueryOrderTool())
        orch._context_manager = ctx  # reuse the pre-bound session store

        msg = UserMessage(
            session_id="idor-s5",
            content="查询订单 ORD-001",
            channel="web",
            user_id="user-999",
        )
        resp = await orch.handle_message(msg)
        assert "身份校验失败" in resp.text_fallback


# ---------------------------------------------------------------------------
# HIGH — question-form replies must not be read as consent
# ---------------------------------------------------------------------------


class TestAffirmationQuestionGuard:
    @pytest.mark.unit
    @pytest.mark.parametrize(
        "reply",
        [
            "确定吗？",
            "确认一下是哪个订单",
            "能确认下金额吗",
            "确定要退款吗？",
            "确认是多少钱",
        ],
    )
    def test_interrogative_is_not_affirm(self, reply: str) -> None:
        """Replies that ASK a question (even containing 确认/确定) are not 'yes'.

        Before the fix these matched the unanchored affirm regex and the
        pending high-risk refund/cancel was executed without consent.
        """
        assert ConfirmationResolver._detect_affirmation(reply) is None

    @pytest.mark.unit
    @pytest.mark.parametrize("reply", ["确认", "确定", "好的", "是的", "可以", "执行"])
    def test_plain_confirmation_still_affirms(self, reply: str) -> None:
        """Genuine standalone confirmations must still resolve to 'affirm' —
        the guard tightens questions, it must not break real consent."""
        assert ConfirmationResolver._detect_affirmation(reply) == "affirm"

    @pytest.mark.unit
    @pytest.mark.parametrize("reply", ["不用了", "取消", "算了", "不确定"])
    def test_negation_still_denies(self, reply: str) -> None:
        assert ConfirmationResolver._detect_affirmation(reply) == "deny"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_question_does_not_execute_pending_refund(self) -> None:
        """End-to-end: a pending high-risk tool must NOT execute when the user
        replies with a clarifying question."""
        executed: list[str] = []

        class _RefundSpy(BaseTool):
            name = "create_refund"
            description = "退款"
            category = "order"
            params_schema: ClassVar[dict] = {"type": "object", "properties": {}}
            permissions = ToolPermission(required_roles=["customer"])

            async def execute(self, params, context):  # type: ignore[no-untyped-def]
                executed.append("create_refund")
                return ToolResult(success=True, data={"refunded": True})

        orch = _build_orchestrator(_EchoEntityTool())
        # Make the spy retrievable by the confirmation resolver.
        orch._tool_injector = ToolInjector(
            {"create_refund": _RefundSpy()},
            [RoutingRule(intent_patterns=["create_refund"], tools=["create_refund"])],
        )

        ctx = SessionContext(session_id="aff-s1", user_id="user-001", channel="web")
        ctx.slots["_pending_confirmation"] = {
            "tool_name": "create_refund",
            "params": {},
            "call_id": "call-create_refund",
        }

        msg = UserMessage(
            session_id="aff-s1", content="确定要退款吗？", channel="web", user_id="user-001"
        )
        await orch._core_handle(msg, ctx)
        assert executed == []  # the irreversible write never ran
        # And the pending confirmation was cleared (one-shot, discarded).
        assert "_pending_confirmation" not in ctx.slots


# ---------------------------------------------------------------------------
# MEDIUM — conversation history is populated each turn
# ---------------------------------------------------------------------------


class TestHistoryGrowth:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_history_grows_across_turns(self) -> None:
        """Two turns on one session must leave both turns in context.history.

        Before the fix nothing ever appended, so the InMemory/Redis backends
        kept history permanently empty and the LLM/intent windows got nothing.
        """
        orch = _build_orchestrator(_EchoEntityTool())
        ctx_mgr: InMemoryContextManager = orch._context_manager

        await orch.handle_message(
            UserMessage(
                session_id="hist-s1",
                content="查询订单 ORD-001",
                channel="web",
                user_id="user-001",
            )
        )
        ctx = ctx_mgr.get("hist-s1")
        assert ctx is not None
        assert len(ctx.history) == 2  # user + assistant turn recorded
        assert ctx.history[0].role == "user"
        assert ctx.history[0].content == "查询订单 ORD-001"
        assert ctx.history[1].role == "assistant"

        await orch.handle_message(
            UserMessage(
                session_id="hist-s1",
                content="查询订单 ORD-002",
                channel="web",
                user_id="user-001",
            )
        )
        ctx2 = ctx_mgr.get("hist-s1")
        assert ctx2 is not None
        assert len(ctx2.history) == 4  # accumulated across turns
        # The second turn's LLM prompt window now contains the first turn.
        history_text = orch._build_history_text(ctx2)
        assert "ORD-001" in history_text


# ---------------------------------------------------------------------------
# MEDIUM — held session locks are never evicted (serial guarantee)
# ---------------------------------------------------------------------------


class TestLockEvictionSkipsHeld:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_held_lock_survives_eviction(self) -> None:
        """A currently-held lock must NOT be evicted when the cap overflows.

        Before the fix the oldest 5000 entries were deleted unconditionally; a
        held lock among them would be replaced by a new Lock(), letting a
        concurrent same-session message run in parallel.
        """
        import asyncio

        orch = _build_orchestrator(_EchoEntityTool())
        orch._SESSION_LOCKS_CAP = 3

        held = asyncio.Lock()
        await held.acquire()
        try:
            orch._session_locks["held-session"] = held
            # Overflow the cap with idle locks so eviction triggers.
            for i in range(10):
                orch._session_locks[f"idle-{i}"] = asyncio.Lock()

            msg = UserMessage(
                session_id="trigger",
                content="查询订单 ORD-001",
                channel="web",
                user_id="user-001",
            )
            await orch.handle_message(msg)

            # The held lock is the SAME object — never replaced.
            assert orch._session_locks.get("held-session") is held
        finally:
            held.release()


# ---------------------------------------------------------------------------
# LOW — internal pending_action payload must not leak into the LLM prompt
# ---------------------------------------------------------------------------


class TestPendingActionNotLeaked:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_confirm_pending_action_stripped_from_prompt(self) -> None:
        """The confirm path stores routing under the non-prefixed
        'pending_action' key; it must be stripped before the LLM prompt."""
        captured: dict[str, str] = {}

        class _CapturingProvider:
            model = "test-model"

            async def chat(self, messages):  # type: ignore[no-untyped-def]
                captured["user_prompt"] = messages[-1].content

                class _R:
                    content = "好的"
                    usage = None

                return _R()

        orch = _build_orchestrator(_EchoEntityTool())
        orch.set_provider(_CapturingProvider())

        from open_chat_shop.core.types import Action

        action = Action(
            type="confirm",
            payload={
                "title": "确认执行：退款",
                "description": "即将执行 create_refund，请确认。",
                "pending_action": {
                    "type": "tool_call",
                    "tool_name": "create_refund",
                    "params": {"order_id": "ORD-001"},
                    "call_id": "call-refund",
                },
            },
        )
        ctx = SessionContext(session_id="leak-s1", user_id="user-001", channel="web")
        ctx.history.append(Message(role="user", content="我要退款"))

        await orch._llm_enhance(action, ctx)
        prompt = captured["user_prompt"]
        # The internal pending_action DICT (call_id + raw params) must NOT reach
        # the provider. (The tool name appears in the human-readable
        # description on purpose, so we assert on the structural leak markers,
        # not the tool name itself.)
        assert "call_id" not in prompt
        assert "call-refund" not in prompt
        assert "pending_action" not in prompt
        assert "'type': 'tool_call'" not in prompt
        # User-facing fields are still present.
        assert "确认执行" in prompt
        assert "即将执行 create_refund" in prompt  # description survives (intended)
