"""LiteLLM-backed provider for real LLM API calls."""
from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import litellm
import yaml

from open_chat_shop.core.exceptions import ProviderError
from open_chat_shop.core.provider import LLMProvider, TransientProviderError
from open_chat_shop.core.types import (
    GenerateConfig,
    LLMChunk,
    LLMResponse,
    Message,
    ProviderCapabilities,
    TokenUsage,
    ToolCall,
    ToolDefinition,
)

logger = logging.getLogger(__name__)

_DEFAULT_CAPABILITIES = ProviderCapabilities(
    tool_calling=True,
    streaming=True,
    vision=False,
    max_context_tokens=4096,
    supported_locales=["zh", "en"],
)


class LiteLLMProvider(LLMProvider):
    """LLM provider backed by LiteLLM for real API calls."""

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        capabilities: ProviderCapabilities | None = None,
    ) -> None:
        self._model = model
        self._api_key = api_key
        self._base_url = base_url
        self._capabilities = capabilities or _DEFAULT_CAPABILITIES
        self.name = model

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        config: GenerateConfig | None = None,
    ) -> LLMResponse:
        kwargs = self._build_kwargs(messages, tools, config, stream=False)
        try:
            response = await litellm.acompletion(**kwargs)
        except Exception as exc:
            raise self._wrap_error(exc) from exc
        return self._parse_response(response)

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        config: GenerateConfig | None = None,
    ) -> AsyncIterator[LLMChunk]:
        kwargs = self._build_kwargs(messages, tools, config, stream=True)
        try:
            response = await litellm.acompletion(**kwargs)
        except Exception as exc:
            raise self._wrap_error(exc) from exc
        async for chunk in response:
            yield self._parse_chunk(chunk)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            response = await litellm.aembedding(
                model=self._model,
                input=texts,
                api_key=self._api_key,
                api_base=self._base_url,
            )
        except Exception as exc:
            raise self._wrap_error(exc) from exc
        return [item["embedding"] for item in response.data]

    def get_capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    def estimate_tokens(self, text: str) -> int:
        try:
            return int(litellm.token_counter(model=self._model, text=text))
        except Exception:
            return max(1, len(text) // 4)

    def _build_kwargs(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None,
        config: GenerateConfig | None,
        *,
        stream: bool,
    ) -> dict[str, Any]:
        formatted_messages = [
            {"role": m.role, "content": m.content} for m in messages
        ]
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": formatted_messages,
            "api_key": self._api_key,
            "api_base": self._base_url,
            "stream": stream,
        }
        if config is not None:
            kwargs["temperature"] = config.temperature
            kwargs["max_tokens"] = config.max_tokens
            if config.stop_sequences:
                kwargs["stop"] = config.stop_sequences
            kwargs["timeout"] = config.timeout_seconds
        if tools and self._capabilities.tool_calling:
            kwargs["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in tools
            ]
        return {k: v for k, v in kwargs.items() if v is not None}

    @staticmethod
    def _parse_response(response: object) -> LLMResponse:
        resp = cast(Any, response)
        choice = resp.choices[0]
        content = choice.message.content or ""

        tool_calls: list[ToolCall] = []
        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                import json

                params = json.loads(tc.function.arguments or "{}")
                tool_calls.append(
                    ToolCall(
                        tool_name=tc.function.name,
                        params=params,
                        call_id=tc.id,
                    )
                )

        usage = TokenUsage(
            prompt_tokens=resp.usage.prompt_tokens,
            completion_tokens=resp.usage.completion_tokens,
            total_tokens=resp.usage.total_tokens,
        )
        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            usage=usage,
            finish_reason=choice.finish_reason or "stop",
        )

    @staticmethod
    def _parse_chunk(chunk: object) -> LLMChunk:
        ch = cast(Any, chunk)
        delta = ch.choices[0].delta
        return LLMChunk(
            content_delta=delta.content or "",
            tool_call_delta=None,
            finish_reason=ch.choices[0].finish_reason,
        )

    def _wrap_error(self, exc: Exception) -> ProviderError:
        """Map a LiteLLM/transport exception to the right ProviderError flavour.

        Transient upstream failures (timeout, connection drop, 5xx, rate limit)
        become ``TransientProviderError`` so ``resilience.RetryPolicy`` retries
        them; everything else (auth, bad request, content policy, parsing) stays
        a plain, non-retryable ``ProviderError``. This mirrors
        ``AnthropicProvider._to_provider_error`` — without it a wrapped transient
        from the LiteLLM fallback path was a plain ``ProviderError`` that matched
        no entry in ``_RETRYABLE`` and so was never retried (audit PROVIDER HIGH).
        """
        if isinstance(exc, TransientProviderError):
            return exc
        cls = (
            TransientProviderError if self._is_transient(exc) else ProviderError
        )
        return cls(
            message=str(exc),
            provider=self._model,
            details={"exception_type": type(exc).__name__},
        )

    @staticmethod
    def _is_transient(exc: Exception) -> bool:
        """Return True if *exc* is a retryable transient upstream failure.

        Raw transport errors (``TimeoutError``/``ConnectionError``/``OSError``)
        are transient. LiteLLM's SDK exceptions are rooted at ``OpenAIError`` and
        are NOT builtin ``OSError`` subclasses, so the retryable ones (timeout,
        connection, 5xx, rate limit) must be matched explicitly or retry misses
        them. Permanent failures (auth, bad request, not found, content policy)
        return False so we fail fast instead of hammering a broken upstream.
        """
        if isinstance(exc, TimeoutError | ConnectionError | OSError):
            return True
        try:
            import httpx
            from litellm.exceptions import (
                APIConnectionError,
                BadGatewayError,
                InternalServerError,
                RateLimitError,
                ServiceUnavailableError,
                Timeout,
            )

            # httpx.TransportError covers connect/read/write/pool timeouts and
            # network errors. LiteLLM is httpx-backed and usually wraps these in
            # its own Timeout/APIConnectionError, but can let some escape raw;
            # they are NOT builtin OSError subclasses, so they must be matched
            # explicitly or retry would miss them (mirrors AnthropicProvider).
            return isinstance(
                exc,
                Timeout
                | APIConnectionError
                | InternalServerError
                | ServiceUnavailableError
                | BadGatewayError
                | RateLimitError
                | httpx.TransportError,
            )
        except ImportError:  # pragma: no cover - both are hard dependencies
            return False


@dataclass
class ProviderConfig:
    """Configuration for a single LLM provider loaded from YAML."""

    type: str
    model: str
    api_key_env: str = "OPENAI_API_KEY"
    base_url: str | None = None
    max_tokens: int = 4096
    timeout: int = 30
    temperature: float = 0.3
    capabilities: ProviderCapabilities = field(
        default_factory=lambda: _DEFAULT_CAPABILITIES,
    )

    @classmethod
    def from_yaml(cls, path: str | Path) -> list[ProviderConfig]:
        with Path(path).open() as f:
            data = yaml.safe_load(f)
        configs: list[ProviderConfig] = []
        for entry in data.get("providers", []):
            caps_data = entry.get("capabilities", {})
            caps = ProviderCapabilities(
                tool_calling=caps_data.get("tool_calling", True),
                streaming=caps_data.get("streaming", True),
                vision=caps_data.get("vision", False),
                max_context_tokens=entry.get("max_context_tokens", 4096),
                supported_locales=caps_data.get("supported_locales", ["zh", "en"]),
            )
            configs.append(
                cls(
                    type=entry.get("type", "openai"),
                    model=entry["model"],
                    api_key_env=entry.get("api_key_env", "OPENAI_API_KEY"),
                    base_url=entry.get("base_url"),
                    max_tokens=entry.get("max_tokens", 4096),
                    timeout=entry.get("timeout", 30),
                    temperature=entry.get("temperature", 0.3),
                    capabilities=caps,
                )
            )
        return configs


class ProviderFactory:
    """Creates LiteLLMProvider instances from ProviderConfig."""

    @staticmethod
    def create_provider(config: ProviderConfig) -> LiteLLMProvider:
        api_key = os.environ.get(config.api_key_env)
        return LiteLLMProvider(
            model=config.model,
            api_key=api_key,
            base_url=config.base_url,
            capabilities=config.capabilities,
        )
