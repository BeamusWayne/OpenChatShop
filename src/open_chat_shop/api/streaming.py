"""Streaming response pipeline — SSE and WebSocket support."""
from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from open_chat_shop.core.types import AgentMessage, UserMessage

if TYPE_CHECKING:
    from open_chat_shop.channel.base import ChannelAdapter

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


def build_done_event(event: StreamEvent, adapter: ChannelAdapter) -> StreamEvent:
    """Reconstruct the channel-adapted ``done`` event from a stream event.

    The SSE and WebSocket paths both rebuild an :class:`AgentMessage` from the
    streaming ``done`` payload, run it through the channel *adapter*, and
    repackage the adapted result as a ``done`` event. The only thing that
    differs between the two paths is the adapter instance and the wire encoding
    (``to_sse`` vs ``to_json``), so the shared reconstruction lives here and the
    caller picks the encoding.

    ``text_fallback`` is read explicitly (not dug out of ``payload``) because
    rich payloads (order_card, product_list, ...) have no ``content`` key — see
    the ``done`` event emitted in :meth:`StreamingOrchestrator.handle_streaming`.
    """
    agent_msg = AgentMessage(
        message_type=event.data.get("message_type", "text"),
        payload=event.data.get("payload", {}),
        text_fallback=event.data.get("text_fallback", ""),
    )
    channel_msg = adapter.adapt_with_fallback(agent_msg)
    return StreamEvent(
        type="done",
        data={
            "message_type": channel_msg.content_type,
            "payload": channel_msg.payload,
            "suggestions": event.data.get("suggestions", []),
            "requires_confirmation": event.data.get("requires_confirmation", False),
        },
    )


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

            # 4. Done event with full message metadata.
            # text_fallback is carried explicitly so downstream reconstruction
            # does NOT have to dig it out of payload["content"] — rich payloads
            # (order_card, product_list, ...) have no "content" key, so relying
            # on payload would collapse the fallback to "" and lose the tool's
            # computed text (e.g. "找到 N 个商品") when a rich type is downgraded.
            yield StreamEvent(
                type="done",
                data={
                    "message_type": response.message_type,
                    "payload": response.payload,
                    "text_fallback": response.text_fallback,
                    "suggestions": response.suggestions,
                    "requires_confirmation": response.requires_confirmation,
                },
            )

        except Exception:
            logger.exception("Streaming error", extra={"session_id": message.session_id})
            yield StreamEvent(
                type="error",
                data={"message": "处理消息时出错，请稍后重试"},
            )

    async def _stream_llm(
        self, response: AgentMessage
    ) -> AsyncIterator[StreamEvent]:
        """Stream the text_fallback through the provider for chunked output."""
        from open_chat_shop.core.types import Message

        messages = [Message(role="assistant", content=response.text_fallback)]
        provider: Any = self._provider
        async for chunk in provider.stream(messages):
            if chunk.content_delta:
                yield StreamEvent(
                    type="chunk",
                    data={"content_delta": chunk.content_delta},
                )
