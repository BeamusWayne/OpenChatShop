"""Tests for LLM Provider abstraction and cascade strategy."""
from __future__ import annotations

import pytest

from commerce_agent.core.types import (
    Message,
    GenerateConfig,
    ToolDefinition,
)
from commerce_agent.core.provider import (
    MockProvider,
    FailingProvider,
    CascadeStrategy,
)
from commerce_agent.core.exceptions import ProviderError


@pytest.fixture
def mock_provider() -> MockProvider:
    return MockProvider()


@pytest.fixture
def failing_provider() -> FailingProvider:
    return FailingProvider()


@pytest.fixture
def messages() -> list[Message]:
    return [
        Message(role="system", content="You are a helpful assistant."),
        Message(role="user", content="Hello!"),
    ]


class TestMockProvider:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_chat_returns_response(self, mock_provider, messages):
        response = await mock_provider.chat(messages)
        assert response.content == "This is a mock response."
        assert response.finish_reason == "stop"
        assert response.usage.total_tokens > 0

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_chat_with_tools(self, mock_provider, messages):
        tools = [ToolDefinition(
            name="test_tool",
            description="A test tool",
            parameters={"type": "object", "properties": {}},
        )]
        response = await mock_provider.chat(messages, tools=tools)
        assert response.content

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_stream_yields_chunks(self, mock_provider, messages):
        chunks = []
        async for chunk in mock_provider.stream(messages):
            chunks.append(chunk)
        assert len(chunks) > 0
        full_text = "".join(c.content_delta for c in chunks)
        assert "mock" in full_text.lower()
        assert chunks[-1].finish_reason == "stop"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_embed_returns_vectors(self, mock_provider):
        result = await mock_provider.embed(["hello", "world"])
        assert len(result) == 2
        assert len(result[0]) == 384

    @pytest.mark.unit
    def test_capabilities(self, mock_provider):
        caps = mock_provider.get_capabilities()
        assert caps.tool_calling is True
        assert caps.streaming is True
        assert caps.vision is False

    @pytest.mark.unit
    def test_estimate_tokens(self, mock_provider):
        tokens = mock_provider.estimate_tokens("Hello world, this is a test.")
        assert tokens > 0

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_call_log(self, mock_provider, messages):
        await mock_provider.chat(messages)
        await mock_provider.embed(["test"])
        assert len(mock_provider.call_log) == 2
        assert mock_provider.call_log[0]["method"] == "chat"
        assert mock_provider.call_log[1]["method"] == "embed"


class TestFailingProvider:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_chat_raises_provider_error(self, failing_provider, messages):
        with pytest.raises(ProviderError) as exc_info:
            await failing_provider.chat(messages)
        assert exc_info.value.provider == "failing"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_embed_raises_provider_error(self, failing_provider):
        with pytest.raises(ProviderError):
            await failing_provider.embed(["test"])


class TestCascadeStrategy:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_first_provider_succeeds(self, messages):
        mock = MockProvider()
        cascade = CascadeStrategy([mock])
        response, provider_name = await cascade.chat(messages)
        assert response.content == "This is a mock response."
        assert provider_name == "mock"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_cascade_to_second_provider(self, messages):
        failing = FailingProvider()
        mock = MockProvider(default_response="Fallback response")
        cascade = CascadeStrategy([failing, mock])
        response, provider_name = await cascade.chat(messages)
        assert response.content == "Fallback response"
        assert provider_name == "mock"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_all_providers_fail_raises(self, messages):
        cascade = CascadeStrategy([FailingProvider(), FailingProvider()])
        with pytest.raises(ProviderError):
            await cascade.chat(messages)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_cascade_embed(self):
        mock = MockProvider()
        cascade = CascadeStrategy([mock])
        embeddings, provider_name = await cascade.embed(["test"])
        assert len(embeddings) == 1
        assert provider_name == "mock"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_cascade_without_tools_when_not_supported(self):
        """Provider without tool_calling should receive tools=None."""
        class NoToolProvider(MockProvider):
            def get_capabilities(self):
                from commerce_agent.core.types import ProviderCapabilities
                return ProviderCapabilities(
                    tool_calling=False,
                    streaming=True,
                    vision=False,
                    max_context_tokens=4096,
                    supported_locales=["en"],
                )

        provider = NoToolProvider()
        cascade = CascadeStrategy([provider])
        tools = [ToolDefinition(
            name="test_tool",
            description="test",
            parameters={"type": "object"},
        )]
        msgs = [Message(role="user", content="test")]
        response, _ = await cascade.chat(msgs, tools=tools)
        # Should succeed — tools silently dropped for non-tool-calling provider
        assert response.content
