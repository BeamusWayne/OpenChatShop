"""Tests for LiteLLMProvider, ProviderConfig, and ProviderFactory."""
from __future__ import annotations

import os
import tempfile
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from commerce_agent.core.exceptions import ProviderError
from commerce_agent.core.litellm_provider import (
    LiteLLMProvider,
    ProviderConfig,
    ProviderFactory,
)
from commerce_agent.core.types import (
    GenerateConfig,
    LLMChunk,
    LLMResponse,
    Message,
    ProviderCapabilities,
    TokenUsage,
    ToolDefinition,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_messages() -> list[Message]:
    return [
        Message(role="system", content="You are a helpful assistant."),
        Message(role="user", content="Hello!"),
    ]


def _mock_completion_response(
    content: str = "Hi there!",
    finish_reason: str = "stop",
    prompt_tokens: int = 10,
    completion_tokens: int = 5,
) -> MagicMock:
    message = MagicMock()
    message.content = content
    message.tool_calls = None

    choice = MagicMock()
    choice.message = message
    choice.finish_reason = finish_reason

    usage = MagicMock()
    usage.prompt_tokens = prompt_tokens
    usage.completion_tokens = completion_tokens
    usage.total_tokens = prompt_tokens + completion_tokens

    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = usage
    return resp


def _mock_embedding_response(embeddings: list[list[float]] | None = None) -> MagicMock:
    if embeddings is None:
        embeddings = [[0.1, 0.2, 0.3]]
    data = [{"embedding": e} for e in embeddings]
    resp = MagicMock()
    resp.data = data
    return resp


def _mock_stream_chunks(text_parts: list[str]) -> list[MagicMock]:
    chunks = []
    for i, part in enumerate(text_parts):
        delta = MagicMock()
        delta.content = part
        choice = MagicMock()
        choice.delta = delta
        choice.finish_reason = "stop" if i == len(text_parts) - 1 else None
        chunk = MagicMock()
        chunk.choices = [choice]
        chunks.append(chunk)
    return chunks


async def _async_gen(items: list[Any]):
    for item in items:
        yield item


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def provider() -> LiteLLMProvider:
    return LiteLLMProvider(model="gpt-4o-mini", api_key="test-key")


@pytest.fixture
def no_tool_provider() -> LiteLLMProvider:
    caps = ProviderCapabilities(
        tool_calling=False,
        streaming=True,
        vision=False,
        max_context_tokens=4096,
        supported_locales=["en"],
    )
    return LiteLLMProvider(model="gpt-4o-mini", api_key="test-key", capabilities=caps)


# ---------------------------------------------------------------------------
# chat
# ---------------------------------------------------------------------------


class TestChat:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_returns_llm_response(self, provider: LiteLLMProvider) -> None:
        mock_resp = _mock_completion_response()
        with patch("litellm.acompletion", new_callable=AsyncMock, return_value=mock_resp):
            result = await provider.chat(_make_messages())

        assert isinstance(result, LLMResponse)
        assert result.content == "Hi there!"
        assert result.finish_reason == "stop"
        assert result.usage is not None
        assert result.usage.total_tokens == 15

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_passes_messages_in_correct_format(self, provider: LiteLLMProvider) -> None:
        mock_resp = _mock_completion_response()
        with patch("litellm.acompletion", new_callable=AsyncMock, return_value=mock_resp) as mock_ac:
            await provider.chat(_make_messages())

        call_kwargs = mock_ac.call_args[1]
        msgs = call_kwargs["messages"]
        assert msgs[0]["role"] == "system"
        assert msgs[0]["content"] == "You are a helpful assistant."
        assert msgs[1]["role"] == "user"
        assert msgs[1]["content"] == "Hello!"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_passes_tools_when_capable(self, provider: LiteLLMProvider) -> None:
        mock_resp = _mock_completion_response()
        tools = [ToolDefinition(
            name="search_products",
            description="Search for products",
            parameters={"type": "object", "properties": {"query": {"type": "string"}}},
        )]
        with patch("litellm.acompletion", new_callable=AsyncMock, return_value=mock_resp) as mock_ac:
            await provider.chat(_make_messages(), tools=tools)

        call_kwargs = mock_ac.call_args[1]
        assert "tools" in call_kwargs
        assert call_kwargs["tools"][0]["function"]["name"] == "search_products"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_omits_tools_when_not_capable(self, no_tool_provider: LiteLLMProvider) -> None:
        mock_resp = _mock_completion_response()
        tools = [ToolDefinition(name="search", description="search", parameters={"type": "object"})]
        with patch("litellm.acompletion", new_callable=AsyncMock, return_value=mock_resp) as mock_ac:
            await no_tool_provider.chat(_make_messages(), tools=tools)

        assert "tools" not in mock_ac.call_args[1]

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_applies_generate_config(self, provider: LiteLLMProvider) -> None:
        mock_resp = _mock_completion_response()
        config = GenerateConfig(temperature=0.7, max_tokens=100, timeout_seconds=60)
        with patch("litellm.acompletion", new_callable=AsyncMock, return_value=mock_resp) as mock_ac:
            await provider.chat(_make_messages(), config=config)

        kw = mock_ac.call_args[1]
        assert kw["temperature"] == 0.7
        assert kw["max_tokens"] == 100
        assert kw["timeout"] == 60

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_raises_provider_error_on_exception(self, provider: LiteLLMProvider) -> None:
        with patch("litellm.acompletion", new_callable=AsyncMock, side_effect=Exception("API error")):
            with pytest.raises(ProviderError) as exc_info:
                await provider.chat(_make_messages())

        assert exc_info.value.provider == "gpt-4o-mini"
        assert "API error" in exc_info.value.message


# ---------------------------------------------------------------------------
# stream
# ---------------------------------------------------------------------------


class TestStream:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_yields_llm_chunks(self, provider: LiteLLMProvider) -> None:
        chunks = _mock_stream_chunks(["Hello", " world", "!"])
        with patch("litellm.acompletion", new_callable=AsyncMock, return_value=_async_gen(chunks)):
            result = [c async for c in provider.stream(_make_messages())]

        assert len(result) == 3
        assert all(isinstance(c, LLMChunk) for c in result)
        assert result[0].content_delta == "Hello"
        assert result[-1].finish_reason == "stop"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_stream_raises_provider_error(self, provider: LiteLLMProvider) -> None:
        with patch("litellm.acompletion", new_callable=AsyncMock, side_effect=Exception("Stream error")):
            with pytest.raises(ProviderError):
                _ = [c async for c in provider.stream(_make_messages())]


# ---------------------------------------------------------------------------
# embed
# ---------------------------------------------------------------------------


class TestEmbed:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_returns_vectors(self, provider: LiteLLMProvider) -> None:
        vectors = [[0.1, 0.2], [0.3, 0.4]]
        mock_resp = _mock_embedding_response(vectors)
        with patch("litellm.aembedding", new_callable=AsyncMock, return_value=mock_resp):
            result = await provider.embed(["hello", "world"])

        assert len(result) == 2
        assert result[0] == [0.1, 0.2]
        assert result[1] == [0.3, 0.4]

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_embed_raises_provider_error(self, provider: LiteLLMProvider) -> None:
        with patch("litellm.aembedding", new_callable=AsyncMock, side_effect=Exception("Embed error")):
            with pytest.raises(ProviderError) as exc_info:
                await provider.embed(["test"])

        assert "Embed error" in exc_info.value.message


# ---------------------------------------------------------------------------
# capabilities & token estimation
# ---------------------------------------------------------------------------


class TestCapabilitiesAndTokens:
    @pytest.mark.unit
    def test_default_capabilities(self, provider: LiteLLMProvider) -> None:
        caps = provider.get_capabilities()
        assert caps.tool_calling is True
        assert caps.streaming is True
        assert caps.max_context_tokens == 4096

    @pytest.mark.unit
    def test_custom_capabilities(self, no_tool_provider: LiteLLMProvider) -> None:
        assert no_tool_provider.get_capabilities().tool_calling is False

    @pytest.mark.unit
    def test_name_property(self, provider: LiteLLMProvider) -> None:
        assert provider.name == "gpt-4o-mini"

    @pytest.mark.unit
    def test_estimate_tokens_fallback(self, provider: LiteLLMProvider) -> None:
        with patch("litellm.token_counter", side_effect=Exception("unknown model")):
            tokens = provider.estimate_tokens("Hello world, this is a test.")
        assert tokens == 7  # 28 chars / 4

    @pytest.mark.unit
    def test_estimate_tokens_with_litellm(self, provider: LiteLLMProvider) -> None:
        with patch("litellm.token_counter", return_value=12):
            assert provider.estimate_tokens("Hello world") == 12


# ---------------------------------------------------------------------------
# ProviderConfig.from_yaml
# ---------------------------------------------------------------------------


class TestProviderConfig:
    @pytest.mark.unit
    def test_from_yaml_loads_config(self) -> None:
        yaml_content = (
            "providers:\n"
            "  - name: openai\n"
            "    type: openai\n"
            "    model: gpt-4o-mini\n"
            "    api_key_env: OPENAI_API_KEY\n"
            "    max_context_tokens: 128000\n"
            "    capabilities:\n"
            "      tool_calling: true\n"
            "      streaming: true\n"
            "      vision: true\n"
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            path = f.name

        configs = ProviderConfig.from_yaml(path)
        os.unlink(path)

        assert len(configs) == 1
        cfg = configs[0]
        assert cfg.model == "gpt-4o-mini"
        assert cfg.type == "openai"
        assert cfg.api_key_env == "OPENAI_API_KEY"
        assert cfg.capabilities.tool_calling is True
        assert cfg.capabilities.vision is True
        assert cfg.capabilities.max_context_tokens == 128000

    @pytest.mark.unit
    def test_from_yaml_multiple_providers(self) -> None:
        yaml_content = (
            "providers:\n"
            "  - type: openai\n"
            "    model: gpt-4o-mini\n"
            "  - type: anthropic\n"
            "    model: claude-3-haiku\n"
            "    api_key_env: ANTHROPIC_API_KEY\n"
            "    capabilities:\n"
            "      tool_calling: false\n"
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            path = f.name

        configs = ProviderConfig.from_yaml(path)
        os.unlink(path)

        assert len(configs) == 2
        assert configs[0].model == "gpt-4o-mini"
        assert configs[1].model == "claude-3-haiku"
        assert configs[1].capabilities.tool_calling is False

    @pytest.mark.unit
    def test_from_yaml_defaults(self) -> None:
        yaml_content = "providers:\n  - type: openai\n    model: gpt-4\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            path = f.name

        cfg = ProviderConfig.from_yaml(path)[0]
        os.unlink(path)

        assert cfg.api_key_env == "OPENAI_API_KEY"
        assert cfg.max_tokens == 4096
        assert cfg.timeout == 30
        assert cfg.temperature == 0.3


# ---------------------------------------------------------------------------
# ProviderFactory
# ---------------------------------------------------------------------------


class TestProviderFactory:
    @pytest.mark.unit
    def test_creates_provider_from_config(self) -> None:
        config = ProviderConfig(
            type="openai",
            model="gpt-4o-mini",
            api_key_env="TEST_KEY_LITELLM_FACTORY",
        )
        with patch.dict(os.environ, {"TEST_KEY_LITELLM_FACTORY": "sk-test-123"}):
            provider = ProviderFactory.create_provider(config)

        assert isinstance(provider, LiteLLMProvider)
        assert provider.name == "gpt-4o-mini"

    @pytest.mark.unit
    def test_no_api_key_when_env_missing(self) -> None:
        config = ProviderConfig(
            type="openai",
            model="gpt-4o-mini",
            api_key_env="NONEXISTENT_KEY_XYZ_99999",
        )
        provider = ProviderFactory.create_provider(config)
        assert provider._api_key is None


# ---------------------------------------------------------------------------
# Capability degradation
# ---------------------------------------------------------------------------


class TestCapabilityDegradation:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_tools_not_sent_when_not_supported(self, no_tool_provider: LiteLLMProvider) -> None:
        mock_resp = _mock_completion_response()
        tools = [ToolDefinition(name="search", description="search", parameters={"type": "object"})]
        with patch("litellm.acompletion", new_callable=AsyncMock, return_value=mock_resp) as mock_ac:
            await no_tool_provider.chat(_make_messages(), tools=tools)

        kw = mock_ac.call_args[1]
        assert "tools" not in kw
        assert kw["model"] == "gpt-4o-mini"
        assert len(kw["messages"]) == 2
