"""Unit tests for core data structures and exception hierarchy.

Verifies:
- All dataclasses instantiate with required fields
- Default values work correctly (mutable defaults are independent)
- Exception hierarchy (isinstance checks)
- Error code prefixes (SEC-, PROV-, CTX-, INTENT-, TOOL-, CHAN-)
- SecurityError is not recoverable by default
- ProviderError has .provider attribute
- ContextError has .session_id attribute
- ToolError has .tool_name attribute
- ChannelError has .channel attribute
"""

from __future__ import annotations

from datetime import datetime

import pytest

from open_chat_shop.core.exceptions import (
    ChannelError,
    ContextError,
    IntentError,
    OpenChatShopError,
    ProviderError,
    SecurityError,
    ToolError,
)
from open_chat_shop.core.types import (
    Action,
    AgentMessage,
    Attachment,
    ChannelCapabilities,
    ChannelMessage,
    CheckResult,
    GenerateConfig,
    Intent,
    IntentInfo,
    LLMChunk,
    LLMResponse,
    Message,
    ProviderCapabilities,
    RoutingRule,
    SessionContext,
    TokenBudget,
    TokenUsage,
    ToolCall,
    ToolDefinition,
    ToolPermission,
    ToolResult,
    Transition,
    UserMessage,
    ValidationResult,
)

# ===================================================================
# Data structure instantiation tests
# ===================================================================


@pytest.mark.unit
class TestMessage:
    def test_instantiation_required_fields(self) -> None:
        msg = Message(role="user", content="hello")
        assert msg.role == "user"
        assert msg.content == "hello"
        assert msg.metadata == {}
        assert isinstance(msg.timestamp, datetime)

    def test_metadata_default_is_independent(self) -> None:
        m1 = Message(role="user", content="a")
        m2 = Message(role="user", content="b")
        m1.metadata["key"] = "val"
        assert "key" not in m2.metadata

    def test_explicit_metadata(self) -> None:
        msg = Message(role="assistant", content="hi", metadata={"trace": "x"})
        assert msg.metadata == {"trace": "x"}


@pytest.mark.unit
class TestAttachment:
    def test_required_fields_only(self) -> None:
        att = Attachment(type="image", url="https://example.com/img.png")
        assert att.type == "image"
        assert att.url == "https://example.com/img.png"
        assert att.name is None
        assert att.size_bytes is None
        assert att.mime_type is None

    def test_all_fields(self) -> None:
        att = Attachment(
            type="file",
            url="https://example.com/doc.pdf",
            name="doc.pdf",
            size_bytes=1024,
            mime_type="application/pdf",
        )
        assert att.name == "doc.pdf"
        assert att.size_bytes == 1024
        assert att.mime_type == "application/pdf"


@pytest.mark.unit
class TestUserMessage:
    def test_required_fields(self) -> None:
        um = UserMessage(session_id="s1", content="hi", channel="web")
        assert um.session_id == "s1"
        assert um.content == "hi"
        assert um.channel == "web"
        assert um.user_id is None
        assert um.attachments == []
        assert um.metadata == {}

    def test_with_attachments(self) -> None:
        att = Attachment(type="image", url="http://x.com/a.jpg")
        um = UserMessage(
            session_id="s1",
            content="see this",
            channel="app",
            user_id="u1",
            attachments=[att],
            metadata={"ip": "1.2.3.4"},
        )
        assert len(um.attachments) == 1
        assert um.user_id == "u1"


@pytest.mark.unit
class TestAgentMessage:
    def test_required_fields(self) -> None:
        am = AgentMessage(
            message_type="text",
            payload={"content": "hello"},
            text_fallback="hello",
        )
        assert am.message_type == "text"
        assert am.suggestions == []
        assert am.requires_confirmation is False

    def test_with_suggestions_and_confirmation(self) -> None:
        am = AgentMessage(
            message_type="quick_replies",
            payload={"options": [{"label": "Yes", "value": "yes"}]},
            text_fallback="Choose an option",
            suggestions=["Yes", "No"],
            requires_confirmation=True,
        )
        assert am.suggestions == ["Yes", "No"]
        assert am.requires_confirmation is True


@pytest.mark.unit
class TestIntent:
    def test_required_fields(self) -> None:
        intent = Intent(
            name="query_order",
            display_name="查询订单",
            confidence=0.95,
            source="rule",
        )
        assert intent.name == "query_order"
        assert intent.entities == {}

    def test_with_entities(self) -> None:
        intent = Intent(
            name="request_refund",
            display_name="申请退款",
            confidence=0.8,
            source="llm",
            entities={"order_id": "ORD-001"},
        )
        assert intent.entities["order_id"] == "ORD-001"


@pytest.mark.unit
class TestIntentInfo:
    def test_instantiation(self) -> None:
        info = IntentInfo(
            name="query_order",
            display_name="查询订单",
            description="查询订单状态和详情",
            sample_count=42,
        )
        assert info.sample_count == 42
        assert info.typical_entities == []


@pytest.mark.unit
class TestSessionContext:
    def test_required_fields(self) -> None:
        ctx = SessionContext(session_id="s1", user_id=None, channel="web")
        assert ctx.session_id == "s1"
        assert ctx.history == []
        assert ctx.fsm_state == "idle"
        assert ctx.user_role == "customer"
        assert isinstance(ctx.created_at, datetime)
        assert isinstance(ctx.last_active_at, datetime)

    def test_history_default_is_independent(self) -> None:
        c1 = SessionContext(session_id="s1", user_id=None, channel="web")
        c2 = SessionContext(session_id="s2", user_id=None, channel="app")
        c1.history.append(Message(role="user", content="hi"))
        assert len(c2.history) == 0


@pytest.mark.unit
class TestTokenBudget:
    def test_required_fields(self) -> None:
        tb = TokenBudget(
            total=4096,
            system_prompt=819,
            history=2048,
            tool_results=819,
            slot_entities=410,
            history_used=1500,
        )
        assert tb.needs_compression is False

    def test_needs_compression_explicit(self) -> None:
        tb = TokenBudget(
            total=4096,
            system_prompt=819,
            history=2048,
            tool_results=819,
            slot_entities=410,
            history_used=3000,
            needs_compression=True,
        )
        assert tb.needs_compression is True


@pytest.mark.unit
class TestToolResult:
    def test_success_result(self) -> None:
        tr = ToolResult(success=True, data={"order_id": "ORD-001"})
        assert tr.error is None
        assert tr.sensitive_fields == []
        assert tr.latency_ms == 0

    def test_failure_result(self) -> None:
        tr = ToolResult(success=False, error="not found")
        assert tr.data is None


@pytest.mark.unit
class TestToolDefinition:
    def test_instantiation(self) -> None:
        td = ToolDefinition(
            name="query_order",
            description="查询订单状态",
            parameters={"type": "object", "properties": {"order_id": {"type": "string"}}},
        )
        assert td.name == "query_order"


@pytest.mark.unit
class TestToolCall:
    def test_instantiation(self) -> None:
        tc = ToolCall(tool_name="query_order", params={"order_id": "O1"}, call_id="c1")
        assert tc.call_id == "c1"


@pytest.mark.unit
class TestToolPermission:
    def test_defaults(self) -> None:
        tp = ToolPermission()
        assert tp.required_roles == []
        assert tp.sensitive_output is False
        assert tp.idempotent is True
        assert tp.requires_confirmation is False
        assert tp.confirmation_threshold is None


@pytest.mark.unit
class TestValidationResult:
    def test_valid(self) -> None:
        vr = ValidationResult(valid=True)
        assert vr.errors == []

    def test_invalid(self) -> None:
        vr = ValidationResult(valid=False, errors=["order_id is required"])
        assert len(vr.errors) == 1


@pytest.mark.unit
class TestCheckResult:
    def test_passed(self) -> None:
        cr = CheckResult(passed=True)
        assert cr.reason is None

    def test_failed(self) -> None:
        cr = CheckResult(passed=False, reason="insufficient stock")
        assert cr.reason == "insufficient stock"


@pytest.mark.unit
class TestRoutingRule:
    def test_defaults(self) -> None:
        rr = RoutingRule()
        assert rr.intent_patterns == []
        assert rr.scenario is None
        assert rr.tools == []
        assert rr.priority == 0

    def test_explicit(self) -> None:
        rr = RoutingRule(
            intent_patterns=["query_*"],
            scenario="refund",
            tools=["query_order", "check_refund"],
            priority=10,
        )
        assert rr.scenario == "refund"
        assert rr.priority == 10


@pytest.mark.unit
class TestProviderCapabilities:
    def test_instantiation(self) -> None:
        pc = ProviderCapabilities(
            tool_calling=True,
            streaming=True,
            vision=False,
            max_context_tokens=8192,
        )
        assert pc.supported_locales == []

    def test_with_locales(self) -> None:
        pc = ProviderCapabilities(
            tool_calling=True,
            streaming=True,
            vision=True,
            max_context_tokens=128000,
            supported_locales=["zh", "en"],
        )
        assert "zh" in pc.supported_locales


@pytest.mark.unit
class TestGenerateConfig:
    def test_defaults(self) -> None:
        gc = GenerateConfig()
        assert gc.temperature == 0.3
        assert gc.max_tokens == 4096
        assert gc.stop_sequences == []
        assert gc.timeout_seconds == 30
        assert gc.retries == 2
        assert gc.retry_delay_seconds == 1.0


@pytest.mark.unit
class TestTokenUsage:
    def test_instantiation(self) -> None:
        tu = TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150)
        assert tu.total_tokens == 150


@pytest.mark.unit
class TestLLMResponse:
    def test_required_fields(self) -> None:
        resp = LLMResponse(content="hello")
        assert resp.content == "hello"
        assert resp.tool_calls == []
        assert resp.usage is None
        assert resp.finish_reason == "stop"

    def test_with_tool_calls(self) -> None:
        tc = ToolCall(tool_name="query_order", params={"order_id": "O1"}, call_id="c1")
        tu = TokenUsage(prompt_tokens=50, completion_tokens=20, total_tokens=70)
        resp = LLMResponse(content="", tool_calls=[tc], usage=tu, finish_reason="tool_calls")
        assert len(resp.tool_calls) == 1
        assert resp.finish_reason == "tool_calls"


@pytest.mark.unit
class TestLLMChunk:
    def test_defaults(self) -> None:
        chunk = LLMChunk()
        assert chunk.content_delta == ""
        assert chunk.tool_call_delta is None
        assert chunk.finish_reason is None

    def test_explicit(self) -> None:
        chunk = LLMChunk(content_delta="hello", finish_reason="stop")
        assert chunk.content_delta == "hello"


@pytest.mark.unit
class TestChannelMessage:
    def test_instantiation(self) -> None:
        cm = ChannelMessage(
            channel="web",
            content_type="text",
            payload={"content": "hi"},
        )
        assert cm.was_downgraded is False
        assert cm.original_type is None


@pytest.mark.unit
class TestChannelCapabilities:
    def test_defaults(self) -> None:
        cc = ChannelCapabilities()
        assert cc.supported_types == []
        assert cc.supports_rich_text is False
        assert cc.supports_images is False
        assert cc.supports_forms is False
        assert cc.max_message_length == 4096


@pytest.mark.unit
class TestTransition:
    def test_required_fields(self) -> None:
        t = Transition(from_state="idle", to_state="active", trigger="start")
        assert t.guard is None
        assert t.action is None

    def test_with_guard(self) -> None:
        guard_fn = lambda ctx: True  # noqa: E731
        t = Transition(
            from_state="idle",
            to_state="active",
            trigger="start",
            guard=guard_fn,
        )
        assert t.guard is not None
        assert t.guard(None) is True


@pytest.mark.unit
class TestAction:
    def test_reply_action(self) -> None:
        a = Action(type="reply", payload={"content": "hello", "message_type": "text"})
        assert a.type == "reply"

    def test_default_payload(self) -> None:
        a = Action(type="end")
        assert a.payload == {}


# ===================================================================
# Exception hierarchy tests
# ===================================================================


@pytest.mark.unit
class TestOpenChatShopError:
    def test_instantiation(self) -> None:
        err = OpenChatShopError("TEST-001", "something went wrong")
        assert err.error_code == "TEST-001"
        assert err.message == "something went wrong"
        assert err.details == {}
        assert err.recoverable is True

    def test_with_details(self) -> None:
        err = OpenChatShopError(
            "TEST-002",
            "failure",
            details={"key": "value"},
            recoverable=False,
        )
        assert err.details == {"key": "value"}
        assert err.recoverable is False

    def test_is_exception(self) -> None:
        err = OpenChatShopError("X-001", "msg")
        assert isinstance(err, Exception)


@pytest.mark.unit
class TestSecurityError:
    def test_error_code_prefix(self) -> None:
        err = SecurityError("injection detected")
        assert err.error_code.startswith("SEC-")

    def test_not_recoverable(self) -> None:
        err = SecurityError("attack")
        assert err.recoverable is False

    def test_isinstance_hierarchy(self) -> None:
        err = SecurityError("xss")
        assert isinstance(err, SecurityError)
        assert isinstance(err, OpenChatShopError)
        assert isinstance(err, Exception)

    def test_with_details(self) -> None:
        err = SecurityError("prompt injection", details={"pattern": "ignore previous"})
        assert err.details == {"pattern": "ignore previous"}


@pytest.mark.unit
class TestProviderError:
    def test_error_code_prefix(self) -> None:
        err = ProviderError("timeout", provider="openai")
        assert err.error_code.startswith("PROV-")

    def test_has_provider_attribute(self) -> None:
        err = ProviderError("timeout", provider="anthropic")
        assert err.provider == "anthropic"

    def test_recoverable_by_default(self) -> None:
        err = ProviderError("rate limited", provider="openai")
        assert err.recoverable is True

    def test_isinstance_hierarchy(self) -> None:
        err = ProviderError("fail", provider="ollama")
        assert isinstance(err, ProviderError)
        assert isinstance(err, OpenChatShopError)


@pytest.mark.unit
class TestContextError:
    def test_error_code_prefix(self) -> None:
        err = ContextError("session expired", session_id="s1")
        assert err.error_code.startswith("CTX-")

    def test_has_session_id_attribute(self) -> None:
        err = ContextError("corrupt", session_id="abc-123")
        assert err.session_id == "abc-123"

    def test_isinstance_hierarchy(self) -> None:
        err = ContextError("fail", session_id="s1")
        assert isinstance(err, ContextError)
        assert isinstance(err, OpenChatShopError)


@pytest.mark.unit
class TestIntentError:
    def test_error_code_prefix(self) -> None:
        err = IntentError("classification failed")
        assert err.error_code.startswith("INTENT-")

    def test_recoverable_by_default(self) -> None:
        err = IntentError("low confidence")
        assert err.recoverable is True

    def test_isinstance_hierarchy(self) -> None:
        err = IntentError("fail")
        assert isinstance(err, IntentError)
        assert isinstance(err, OpenChatShopError)


@pytest.mark.unit
class TestToolError:
    def test_error_code_prefix(self) -> None:
        err = ToolError("execution failed", tool_name="query_order")
        assert err.error_code.startswith("TOOL-")

    def test_has_tool_name_attribute(self) -> None:
        err = ToolError("not found", tool_name="cancel_order")
        assert err.tool_name == "cancel_order"

    def test_isinstance_hierarchy(self) -> None:
        err = ToolError("fail", tool_name="search_product")
        assert isinstance(err, ToolError)
        assert isinstance(err, OpenChatShopError)


@pytest.mark.unit
class TestChannelError:
    def test_error_code_prefix(self) -> None:
        err = ChannelError("unsupported type", channel="wechat")
        assert err.error_code.startswith("CHAN-")

    def test_has_channel_attribute(self) -> None:
        err = ChannelError("downgrade failed", channel="miniprogram")
        assert err.channel == "miniprogram"

    def test_isinstance_hierarchy(self) -> None:
        err = ChannelError("fail", channel="web")
        assert isinstance(err, ChannelError)
        assert isinstance(err, OpenChatShopError)


@pytest.mark.unit
class TestExceptionHierarchyDistinctness:
    """Verify that error code prefixes are distinct across exception types."""

    def test_prefixes_are_unique(self) -> None:
        prefixes = set()
        for msg in ["test message a", "test message b"]:
            prefixes.add(SecurityError(msg).error_code.split("-")[0] + "-")
            prefixes.add(ProviderError(msg, provider="p").error_code.split("-")[0] + "-")
            prefixes.add(ContextError(msg, session_id="s").error_code.split("-")[0] + "-")
            prefixes.add(IntentError(msg).error_code.split("-")[0] + "-")
            prefixes.add(ToolError(msg, tool_name="t").error_code.split("-")[0] + "-")
            prefixes.add(ChannelError(msg, channel="c").error_code.split("-")[0] + "-")
        # All 6 prefixes should be distinct
        assert prefixes == {"SEC-", "PROV-", "CTX-", "INTENT-", "TOOL-", "CHAN-"}
