"""Anthropic-compatible provider for GLM (Zhipu AI)."""
from __future__ import annotations

import os
from collections.abc import AsyncIterator

from dotenv import load_dotenv

from open_chat_shop.core.exceptions import ProviderError
from open_chat_shop.core.provider import LLMProvider
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

load_dotenv()


class AnthropicProvider(LLMProvider):
    """Provider using Anthropic SDK against a compatible endpoint (e.g. Zhipu GLM)."""

    name = "anthropic"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ) -> None:
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._base_url = base_url or os.environ.get(
            "ANTHROPIC_BASE_URL", "https://api.anthropic.com",
        )
        self._model = model or os.environ.get("GLM_MODEL", "glm-5.1")

        if not self._api_key:
            raise ProviderError("ANTHROPIC_API_KEY not set", self.name)

    def _get_client(self):
        from anthropic import AsyncAnthropic

        return AsyncAnthropic(
            api_key=self._api_key,
            base_url=self._base_url,
        )

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        config: GenerateConfig | None = None,
    ) -> LLMResponse:
        try:
            client = self._get_client()
            api_messages = [
                {"role": m.role, "content": m.content}
                for m in messages
                if m.role in ("user", "assistant")
            ]

            system_text = ""
            for m in messages:
                if m.role == "system":
                    system_text += m.content + "\n"

            kwargs: dict = {
                "model": self._model,
                "max_tokens": config.max_tokens if config else 2048,
                "messages": api_messages,
            }
            if system_text.strip():
                kwargs["system"] = system_text.strip()

            # Native function calling: forward tool schemas so the model can
            # select a tool and return structured tool_use blocks.
            if tools:
                kwargs["tools"] = [
                    {
                        "name": t.name,
                        "description": t.description,
                        "input_schema": t.parameters,
                    }
                    for t in tools
                ]

            response = await client.messages.create(**kwargs)

            # A response may interleave text and tool_use blocks. Parse both;
            # do not assume the first block is text (tool_use-only is valid).
            text_parts: list[str] = []
            tool_calls: list[ToolCall] = []
            for block in response.content or []:
                block_type = getattr(block, "type", None)
                if block_type == "text":
                    text_parts.append(getattr(block, "text", "") or "")
                elif block_type == "tool_use":
                    tool_calls.append(
                        ToolCall(
                            tool_name=block.name,
                            params=dict(block.input or {}),
                            call_id=block.id,
                        )
                    )

            return LLMResponse(
                content="".join(text_parts),
                tool_calls=tool_calls,
                usage=TokenUsage(
                    prompt_tokens=response.usage.input_tokens,
                    completion_tokens=response.usage.output_tokens,
                    total_tokens=response.usage.input_tokens + response.usage.output_tokens,
                ),
                finish_reason=response.stop_reason or "stop",
            )
        except Exception as e:
            raise ProviderError(str(e), self.name) from e

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        config: GenerateConfig | None = None,
    ) -> AsyncIterator[LLMChunk]:
        try:
            client = self._get_client()
            api_messages = [
                {"role": m.role, "content": m.content}
                for m in messages
                if m.role in ("user", "assistant")
            ]

            system_text = ""
            for m in messages:
                if m.role == "system":
                    system_text += m.content + "\n"

            kwargs: dict = {
                "model": self._model,
                "max_tokens": config.max_tokens if config else 2048,
                "messages": api_messages,
            }
            if system_text.strip():
                kwargs["system"] = system_text.strip()

            async with client.messages.stream(**kwargs) as stream:
                async for text in stream.text_stream:
                    yield LLMChunk(
                        content_delta=text,
                        tool_call_delta=None,
                        finish_reason=None,
                    )

            yield LLMChunk(
                content_delta="",
                tool_call_delta=None,
                finish_reason="stop",
            )
        except Exception as e:
            raise ProviderError(str(e), self.name) from e

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * 384 for _ in texts]

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            tool_calling=True,
            streaming=True,
            vision=False,
            max_context_tokens=128000,
            supported_locales=["zh", "en"],
        )

    def estimate_tokens(self, text: str) -> int:
        return max(1, len(text) // 2)
