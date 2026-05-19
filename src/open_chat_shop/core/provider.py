"""LLM Provider abstraction layer with cascade strategy."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator

from open_chat_shop.core.types import (
    Message,
    ToolDefinition,
    GenerateConfig,
    LLMResponse,
    LLMChunk,
    TokenUsage,
    ProviderCapabilities,
)
from open_chat_shop.core.exceptions import ProviderError

import logging

logger = logging.getLogger(__name__)


class LLMProvider(ABC):
    """Abstract base class for all LLM providers.

    Implementations wrap LiteLLM or direct API calls.
    This layer handles cascade strategy and capability degradation.
    """

    name: str

    @abstractmethod
    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        config: GenerateConfig | None = None,
    ) -> LLMResponse:
        """Synchronous chat interface. tools=None disables function calling."""

    @abstractmethod
    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        config: GenerateConfig | None = None,
    ) -> AsyncIterator[LLMChunk]:
        """Streaming chat interface."""

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Text vectorization."""

    @abstractmethod
    def get_capabilities(self) -> ProviderCapabilities:
        """Declare provider capabilities."""

    @abstractmethod
    def estimate_tokens(self, text: str) -> int:
        """Estimate token consumption for budget management."""


class CascadeStrategy:
    """Provider cascade with capability degradation.

    Levels are tried in order. If a level fails (ProviderError),
    the next level is attempted. Capability degradation:
    - tool_calling → text parsing
    - streaming → sync
    - vision → reject
    """

    def __init__(self, providers: list[LLMProvider]) -> None:
        self._providers = providers

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        config: GenerateConfig | None = None,
    ) -> tuple[LLMResponse, str]:
        """Try providers in cascade order.

        Returns (response, provider_name).
        Raises ProviderError if all providers fail.
        """
        last_error: ProviderError | None = None
        for provider in self._providers:
            try:
                caps = provider.get_capabilities()
                provider_tools = tools if caps.tool_calling else None
                response = await provider.chat(messages, provider_tools, config)
                return response, provider.name
            except ProviderError as e:
                logger.warning(
                    "Provider %s failed, cascading to next",
                    provider.name,
                    extra={"provider": provider.name, "error": e.message},
                )
                last_error = e

        raise last_error or ProviderError("All providers failed", "cascade")

    async def embed(self, texts: list[str]) -> tuple[list[list[float]], str]:
        """Try providers for embedding. Returns (embeddings, provider_name)."""
        last_error: ProviderError | None = None
        for provider in self._providers:
            try:
                embeddings = await provider.embed(texts)
                return embeddings, provider.name
            except ProviderError as e:
                logger.warning(
                    "Embed provider %s failed", provider.name,
                    extra={"provider": provider.name, "error": e.message},
                )
                last_error = e

        raise last_error or ProviderError("All embed providers failed", "cascade")


class MockProvider(LLMProvider):
    """Mock provider for testing and development."""

    name = "mock"

    def __init__(
        self,
        default_response: str = "This is a mock response.",
        default_embeddings: list[list[float]] | None = None,
    ) -> None:
        self._default_response = default_response
        self._default_embeddings = default_embeddings or [[0.1] * 384]
        self._call_log: list[dict] = []

    @property
    def call_log(self) -> list[dict]:
        return list(self._call_log)

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        config: GenerateConfig | None = None,
    ) -> LLMResponse:
        self._call_log.append({
            "method": "chat",
            "messages_count": len(messages),
            "tools_count": len(tools) if tools else 0,
        })
        return LLMResponse(
            content=self._default_response,
            tool_calls=[],
            usage=TokenUsage(prompt_tokens=10, completion_tokens=20, total_tokens=30),
            finish_reason="stop",
        )

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        config: GenerateConfig | None = None,
    ) -> AsyncIterator[LLMChunk]:
        self._call_log.append({
            "method": "stream",
            "messages_count": len(messages),
        })
        words = self._default_response.split()
        for i, word in enumerate(words):
            yield LLMChunk(
                content_delta=word + (" " if i < len(words) - 1 else ""),
                tool_call_delta=None,
                finish_reason="stop" if i == len(words) - 1 else None,
            )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self._call_log.append({"method": "embed", "texts_count": len(texts)})
        return [self._default_embeddings[0] for _ in texts]

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            tool_calling=True,
            streaming=True,
            vision=False,
            max_context_tokens=4096,
            supported_locales=["zh", "en"],
        )

    def estimate_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)


class FailingProvider(LLMProvider):
    """Provider that always fails, used for testing cascade."""

    name = "failing"

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        config: GenerateConfig | None = None,
    ) -> LLMResponse:
        raise ProviderError("Provider intentionally failed", self.name)

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        config: GenerateConfig | None = None,
    ) -> AsyncIterator[LLMChunk]:
        raise ProviderError("Provider intentionally failed", self.name)
        yield  # noqa: unreachable — makes this an async generator

    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise ProviderError("Provider intentionally failed", self.name)

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            tool_calling=False,
            streaming=False,
            vision=False,
            max_context_tokens=0,
            supported_locales=[],
        )

    def estimate_tokens(self, text: str) -> int:
        return 0
