"""LiteLLM-backed provider for real LLM API calls."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator

import litellm
import yaml

from commerce_agent.core.exceptions import ProviderError
from commerce_agent.core.provider import LLMProvider
from commerce_agent.core.types import (
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

    @property
    def name(self) -> str:
        return self._model

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
            return litellm.token_counter(model=self._model, text=text)
        except Exception:
            return max(1, len(text) // 4)

    def _build_kwargs(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None,
        config: GenerateConfig | None,
        *,
        stream: bool,
    ) -> dict:
        formatted_messages = [
            {"role": m.role, "content": m.content} for m in messages
        ]
        kwargs: dict = {
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
        choice = response.choices[0]
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
            prompt_tokens=response.usage.prompt_tokens,
            completion_tokens=response.usage.completion_tokens,
            total_tokens=response.usage.total_tokens,
        )
        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            usage=usage,
            finish_reason=choice.finish_reason or "stop",
        )

    @staticmethod
    def _parse_chunk(chunk: object) -> LLMChunk:
        delta = chunk.choices[0].delta
        return LLMChunk(
            content_delta=delta.content or "",
            tool_call_delta=None,
            finish_reason=chunk.choices[0].finish_reason,
        )

    def _wrap_error(self, exc: Exception) -> ProviderError:
        return ProviderError(
            message=str(exc),
            provider=self._model,
            details={"exception_type": type(exc).__name__},
        )


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
