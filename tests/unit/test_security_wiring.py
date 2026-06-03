"""Regression tests for the 4-layer security chain wiring (audit HIGH-5).

The SecurityGuard defines four layers (injection, PII masking, RBAC,
output sanitization) but before this fix only layer 1 (injection) was
actually enforced on the production path:

  - Layer 2 (PII) only logged; the masked text was never written back, so
    raw PII flowed to the LLM / history / tools.
  - Layer 3 (check_permission) had zero callers.
  - Layer 4 (sanitize_output) had zero callers.

These tests pin the *wired* behaviour through the orchestrator:
  - PII in user input is masked before any downstream module sees it.
  - check_permission gates every tool execution by role.
  - sanitize_output masks sensitive fields in tool results before output.
"""
from __future__ import annotations

import pytest

from open_chat_shop.core.context import InMemoryContextManager
from open_chat_shop.core.orchestrator import DialogueOrchestrator
from open_chat_shop.core.security import SecurityGuard
from open_chat_shop.core.tool import BaseTool
from open_chat_shop.core.types import (
    Action,
    AgentMessage,
    Intent,
    SessionContext,
    ToolPermission,
    ToolResult,
    UserMessage,
)

# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _SpyIntentEngine:
    """Captures the message content handed to classify()."""

    def __init__(self) -> None:
        self.seen_content: str | None = None

    async def classify(self, message: UserMessage, context: SessionContext) -> Intent:
        self.seen_content = message.content
        return Intent(
            name="fallback",
            display_name="兜底",
            confidence=0.0,
            source="rule",
            entities={},
        )


class _FixedIntentEngine:
    """Always returns the same intent (drives the tool path)."""

    async def classify(self, message: UserMessage, context: SessionContext) -> Intent:
        return Intent(
            name="do_thing",
            display_name="做事",
            confidence=1.0,
            source="rule",
            entities={},
        )


class _StubInjector:
    """Returns a fixed tool list, bypassing ToolInjector's own RBAC filter.

    This guarantees the tool reaches _execute_tool so the SecurityGuard
    permission gate is what we're actually exercising.
    """

    def __init__(self, tools: list[BaseTool]) -> None:
        self._tools = tools

    async def inject(self, intent: Intent, context: SessionContext) -> list[BaseTool]:
        return list(self._tools)


class _StubStrategy:
    """Always emits a tool_call action for the given tool."""

    def __init__(self, tool_name: str, params: dict | None = None) -> None:
        self._tool_name = tool_name
        self._params = params or {}

    async def decide(self, intent: Intent, context: SessionContext, tools) -> Action:
        return Action(
            type="tool_call",
            payload={
                "tool_name": self._tool_name,
                "params": dict(self._params),
                "call_id": "call-test",
            },
        )


class _FlagTool(BaseTool):
    """A tool that records whether it executed and returns fixed data."""

    def __init__(self, name: str, data: dict) -> None:
        self.name = name
        self.description = "test tool"
        self.category = "test"
        self.params_schema = {"type": "object", "properties": {}}
        self.permissions = ToolPermission(required_roles=["*"])
        self.executed = False
        self._data = data

    async def execute(self, params: dict, context: SessionContext) -> ToolResult:
        self.executed = True
        return ToolResult(success=True, data=dict(self._data))


# ---------------------------------------------------------------------------
# Layer 2 — PII masking
# ---------------------------------------------------------------------------


class TestPiiMasking:
    def test_check_input_returns_masked_message(self) -> None:
        guard = SecurityGuard({})
        msg = UserMessage(
            session_id="s1",
            content="我的手机号13912345678 邮箱 test@example.com",
            channel="web",
        )
        result = guard.check_input(msg)
        assert isinstance(result, UserMessage)
        assert "[PHONE]" in result.content
        assert "[EMAIL]" in result.content
        assert "13912345678" not in result.content
        assert "test@example.com" not in result.content

    def test_check_input_does_not_mutate_original(self) -> None:
        guard = SecurityGuard({})
        msg = UserMessage(session_id="s1", content="手机13912345678", channel="web")
        guard.check_input(msg)
        # Original message is untouched (immutability).
        assert msg.content == "手机13912345678"

    def test_check_input_clean_content_passes_through(self) -> None:
        guard = SecurityGuard({})
        msg = UserMessage(session_id="s1", content="我想查订单 ORD-001", channel="web")
        result = guard.check_input(msg)
        assert result.content == "我想查订单 ORD-001"

    @pytest.mark.asyncio
    async def test_pii_masked_before_intent_classification(self) -> None:
        """The orchestrator must hand masked content to downstream modules."""
        spy = _SpyIntentEngine()
        orch = DialogueOrchestrator(
            security_guard=SecurityGuard({}),
            context_manager=InMemoryContextManager(),
            intent_engine=spy,
            tool_injector=_StubInjector([]),
            strategy=_StubStrategy("noop"),
        )
        msg = UserMessage(
            session_id="s1",
            content="请联系我 13912345678",
            channel="web",
        )
        await orch.handle_message(msg)
        assert spy.seen_content is not None
        assert "[PHONE]" in spy.seen_content
        assert "13912345678" not in spy.seen_content


# ---------------------------------------------------------------------------
# Layer 3 — RBAC permission gate
# ---------------------------------------------------------------------------


def _build_tool_orchestrator(
    rbac_roles: list[dict],
    tool: BaseTool,
) -> DialogueOrchestrator:
    return DialogueOrchestrator(
        security_guard=SecurityGuard({"rbac": {"roles": rbac_roles}}),
        context_manager=InMemoryContextManager(),
        intent_engine=_FixedIntentEngine(),
        tool_injector=_StubInjector([tool]),
        strategy=_StubStrategy(tool.name),
    )


class TestPermissionGate:
    @pytest.mark.asyncio
    async def test_blocks_unauthorized_tool(self) -> None:
        tool = _FlagTool("danger_tool", {"ok": True})
        # customer role is NOT granted danger_tool.
        orch = _build_tool_orchestrator(
            [{"name": "customer", "tools": ["query_order"]}], tool
        )
        msg = UserMessage(session_id="s1", content="do it", channel="web")
        resp = await orch.handle_message(msg)
        assert isinstance(resp, AgentMessage)
        assert "权限" in resp.text_fallback
        assert tool.executed is False  # gate ran *before* execution

    @pytest.mark.asyncio
    async def test_allows_authorized_tool(self) -> None:
        tool = _FlagTool("danger_tool", {"ok": True})
        orch = _build_tool_orchestrator(
            [{"name": "customer", "tools": ["danger_tool"]}], tool
        )
        msg = UserMessage(session_id="s1", content="do it", channel="web")
        resp = await orch.handle_message(msg)
        assert isinstance(resp, AgentMessage)
        assert tool.executed is True
        assert "权限" not in resp.text_fallback


# ---------------------------------------------------------------------------
# Layer 4 — output sanitization
# ---------------------------------------------------------------------------


class TestOutputSanitization:
    @pytest.mark.asyncio
    async def test_sensitive_result_fields_are_masked(self) -> None:
        tool = _FlagTool("get_profile", {"name": "Alice", "phone": "13912345678"})
        orch = _build_tool_orchestrator(
            [{"name": "customer", "tools": ["get_profile"]}], tool
        )
        msg = UserMessage(session_id="s1", content="profile", channel="web")
        resp = await orch.handle_message(msg)
        assert "13912345678" not in resp.text_fallback
        assert "***" in resp.text_fallback
