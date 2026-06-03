"""Tests for native function-calling in AnthropicProvider (audit HIGH-10).

The provider accepted a ``tools`` argument but never forwarded it to the
API, hard-coded ``tool_calls=[]`` and declared ``tool_calling=False`` — so
the model could never select a tool and the structured tool_use output was
discarded. These tests pin the real wiring at the provider layer:

  - ToolDefinitions are forwarded as Anthropic tool schemas;
  - tool_use blocks in the response are parsed into LLMResponse.tool_calls;
  - text and tool_use blocks coexist (mixed responses parse correctly);
  - the provider advertises tool_calling=True.

Scope note: this wires FC at the *provider* layer. Routing the orchestrator
through native FC (replacing the strategy if/else) is tracked separately.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from open_chat_shop.core.anthropic_provider import AnthropicProvider
from open_chat_shop.core.types import Message, ToolDefinition


class _Block:
    def __init__(self, type, text=None, id=None, name=None, input=None) -> None:
        self.type = type
        self.text = text
        self.id = id
        self.name = name
        self.input = input


class _Usage:
    def __init__(self, i: int, o: int) -> None:
        self.input_tokens = i
        self.output_tokens = o


class _Resp:
    def __init__(self, content, stop_reason="end_turn") -> None:
        self.content = content
        self.stop_reason = stop_reason
        self.usage = _Usage(10, 20)


def _provider(resp: _Resp):
    provider = AnthropicProvider(api_key="test-key", base_url="http://x", model="glm-test")
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=resp)
    provider._get_client = lambda: client  # type: ignore[method-assign]
    return provider, client


_TOOL = ToolDefinition(
    name="query_order",
    description="Query an order by id",
    parameters={"type": "object", "properties": {"order_id": {"type": "string"}}},
)


class TestToolUseParsing:
    @pytest.mark.asyncio
    async def test_tool_use_block_becomes_tool_call(self) -> None:
        resp = _Resp(
            [
                _Block("text", text="好的我来查询"),
                _Block("tool_use", id="toolu_1", name="query_order", input={"order_id": "ORD-1"}),
            ],
            stop_reason="tool_use",
        )
        provider, _ = _provider(resp)
        result = await provider.chat([Message(role="user", content="查订单")], tools=[_TOOL])
        assert len(result.tool_calls) == 1
        call = result.tool_calls[0]
        assert call.tool_name == "query_order"
        assert call.params == {"order_id": "ORD-1"}
        assert call.call_id == "toolu_1"
        # Text block still surfaces as content.
        assert result.content == "好的我来查询"
        assert result.finish_reason == "tool_use"

    @pytest.mark.asyncio
    async def test_text_only_response_has_no_tool_calls(self) -> None:
        resp = _Resp([_Block("text", text="您好")])
        provider, _ = _provider(resp)
        result = await provider.chat([Message(role="user", content="hi")])
        assert result.tool_calls == []
        assert result.content == "您好"
        assert result.usage.total_tokens == 30

    @pytest.mark.asyncio
    async def test_multiple_tool_use_blocks(self) -> None:
        resp = _Resp(
            [
                _Block("tool_use", id="t1", name="query_order", input={"order_id": "A"}),
                _Block("tool_use", id="t2", name="query_logistics", input={"order_id": "A"}),
            ],
            stop_reason="tool_use",
        )
        provider, _ = _provider(resp)
        result = await provider.chat([Message(role="user", content="x")], tools=[_TOOL])
        assert [c.tool_name for c in result.tool_calls] == ["query_order", "query_logistics"]
        # A tool_use-only response must not raise on missing text block.
        assert result.content == ""


class TestToolSchemaForwarding:
    @pytest.mark.asyncio
    async def test_tools_forwarded_as_schema(self) -> None:
        resp = _Resp([_Block("text", text="ok")])
        provider, client = _provider(resp)
        await provider.chat([Message(role="user", content="x")], tools=[_TOOL])
        kwargs = client.messages.create.call_args.kwargs
        assert "tools" in kwargs
        assert kwargs["tools"] == [
            {
                "name": "query_order",
                "description": "Query an order by id",
                "input_schema": _TOOL.parameters,
            }
        ]

    @pytest.mark.asyncio
    async def test_no_tools_omits_tools_kwarg(self) -> None:
        resp = _Resp([_Block("text", text="ok")])
        provider, client = _provider(resp)
        await provider.chat([Message(role="user", content="x")])
        assert "tools" not in client.messages.create.call_args.kwargs


class TestCapabilities:
    def test_advertises_tool_calling(self) -> None:
        provider = AnthropicProvider(api_key="test-key")
        assert provider.get_capabilities().tool_calling is True
