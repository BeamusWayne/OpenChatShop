"""Streaming response pipeline — SSE and WebSocket support."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from open_chat_shop.core.types import AgentMessage, LLMChunk, UserMessage

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Stream event
# ---------------------------------------------------------------------------


@dataclass
class StreamEvent:
    """A single event in the streaming response pipeline."""

    type: str  # "chunk" | "done" | "error" | "typing"
    data: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        """Serialize to JSON string for wire transmission."""
        return json.dumps({"type": self.type, "data": self.data}, ensure_ascii=False)

    def to_sse(self) -> str:
        """Format as Server-Sent Events frame: ``data: JSON\\n\\n``."""
        return f"data: {self.to_json()}\n\n"


# ---------------------------------------------------------------------------
# Streaming orchestrator
# ---------------------------------------------------------------------------


class StreamingOrchestrator:
    """Wraps a DialogueOrchestrator to add streaming capability."""

    def __init__(self, orchestrator: Any, provider: Any | None = None) -> None:
        self._orchestrator = orchestrator
        self._provider = provider

    async def handle_streaming(
        self,
        message: UserMessage,
    ) -> AsyncIterator[StreamEvent]:
        """Yield StreamEvent objects for a single user message.

        1. typing indicator
        2. For non-LLM paths: single chunk + done
        3. For LLM paths: incremental chunks + done
        4. On error: error event
        """
        # 1. Typing indicator
        yield StreamEvent(type="typing", data={"status": "thinking"})

        try:
            # 2. Delegate to the underlying orchestrator
            response: AgentMessage = await self._orchestrator.handle_message(message)

            # 3. If we have a streaming provider, stream the text content
            if self._provider is not None and response.text_fallback:
                async for chunk in self._stream_llm(response):
                    yield chunk
            else:
                # Non-LLM: yield the full response as one chunk
                yield StreamEvent(
                    type="chunk",
                    data={"content_delta": response.text_fallback},
                )

            # 4. Done event with full message metadata
            yield StreamEvent(
                type="done",
                data={
                    "message_type": response.message_type,
                    "payload": response.payload,
                    "suggestions": response.suggestions,
                    "requires_confirmation": response.requires_confirmation,
                },
            )

        except Exception as exc:
            logger.exception("Streaming error", extra={"session_id": message.session_id})
            yield StreamEvent(
                type="error",
                data={"message": str(exc)},
            )

    async def _stream_llm(
        self, response: AgentMessage
    ) -> AsyncIterator[StreamEvent]:
        """Stream the text_fallback through the provider for chunked output."""
        from open_chat_shop.core.types import Message

        messages = [Message(role="assistant", content=response.text_fallback)]
        async for chunk in self._provider.stream(messages):
            if chunk.content_delta:
                yield StreamEvent(
                    type="chunk",
                    data={"content_delta": chunk.content_delta},
                )
