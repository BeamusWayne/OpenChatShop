"""Unit tests for streaming response pipeline."""
from __future__ import annotations

import json

import pytest

from open_chat_shop.api.streaming import StreamEvent, StreamingOrchestrator
from open_chat_shop.core.provider import MockProvider
from open_chat_shop.core.types import AgentMessage, UserMessage

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _StubOrchestrator:
    """Minimal async stub returning a fixed AgentMessage."""

    def __init__(self, response_text: str = "pong") -> None:
        self._response_text = response_text

    async def handle_message(self, message: UserMessage) -> AgentMessage:
        return AgentMessage(
            message_type="text",
            payload={"content": self._response_text},
            text_fallback=self._response_text,
        )


class _FailingOrchestrator:
    """Orchestrator that always raises."""

    async def handle_message(self, message: UserMessage) -> AgentMessage:
        raise RuntimeError("boom")


# ---------------------------------------------------------------------------
# StreamEvent
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStreamEvent:
    def test_chunk_event(self) -> None:
        event = StreamEvent(type="chunk", data={"content_delta": "hello"})
        assert event.type == "chunk"
        assert event.data["content_delta"] == "hello"

    def test_done_event(self) -> None:
        event = StreamEvent(type="done", data={"message_type": "text"})
        assert event.type == "done"
        assert event.data["message_type"] == "text"

    def test_error_event(self) -> None:
        event = StreamEvent(type="error", data={"message": "oops"})
        assert event.type == "error"
        assert event.data["message"] == "oops"

    def test_typing_event(self) -> None:
        event = StreamEvent(type="typing", data={"status": "thinking"})
        assert event.type == "typing"

    def test_to_json_roundtrip(self) -> None:
        event = StreamEvent(type="chunk", data={"content_delta": "hi"})
        parsed = json.loads(event.to_json())
        assert parsed["type"] == "chunk"
        assert parsed["data"]["content_delta"] == "hi"

    def test_to_sse_format(self) -> None:
        event = StreamEvent(type="chunk", data={"content_delta": "hi"})
        sse = event.to_sse()
        assert sse.startswith("data: ")
        assert sse.endswith("\n\n")
        payload = sse[len("data: "):-2]
        parsed = json.loads(payload)
        assert parsed["type"] == "chunk"


# ---------------------------------------------------------------------------
# StreamingOrchestrator
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
class TestStreamingOrchestrator:
    async def test_yields_typing_indicator_first(self) -> None:
        orch = StreamingOrchestrator(_StubOrchestrator())
        msg = UserMessage(session_id="s1", content="hi", channel="web")
        events = [e async for e in orch.handle_streaming(msg)]
        assert events[0].type == "typing"
        assert events[0].data["status"] == "thinking"

    async def test_yields_done_event_last(self) -> None:
        orch = StreamingOrchestrator(_StubOrchestrator())
        msg = UserMessage(session_id="s1", content="hi", channel="web")
        events = [e async for e in orch.handle_streaming(msg)]
        assert events[-1].type == "done"
        assert events[-1].data["message_type"] == "text"

    async def test_non_llm_single_chunk(self) -> None:
        orch = StreamingOrchestrator(_StubOrchestrator(response_text="hello world"))
        msg = UserMessage(session_id="s1", content="hi", channel="web")
        events = [e async for e in orch.handle_streaming(msg)]
        # typing, chunk, done
        assert len(events) == 3
        assert events[1].type == "chunk"
        assert events[1].data["content_delta"] == "hello world"

    async def test_with_mock_provider_streams_words(self) -> None:
        provider = MockProvider(default_response="one two three")
        orch = StreamingOrchestrator(
            _StubOrchestrator(response_text="one two three"),
            provider=provider,
        )
        msg = UserMessage(session_id="s1", content="hi", channel="web")
        events = [e async for e in orch.handle_streaming(msg)]
        # typing, chunk*3, done
        chunk_events = [e for e in events if e.type == "chunk"]
        assert len(chunk_events) == 3
        deltas = [e.data["content_delta"] for e in chunk_events]
        assert deltas[0] == "one "
        assert deltas[1] == "two "
        assert deltas[2] == "three"

    async def test_error_event_on_exception(self) -> None:
        orch = StreamingOrchestrator(_FailingOrchestrator())
        msg = UserMessage(session_id="s1", content="hi", channel="web")
        events = [e async for e in orch.handle_streaming(msg)]
        # typing, error
        assert len(events) == 2
        assert events[1].type == "error"
        assert "出错" in events[1].data["message"]

    async def test_done_contains_full_metadata(self) -> None:
        orch = StreamingOrchestrator(
            _StubOrchestrator(response_text="reply"),
        )
        msg = UserMessage(session_id="s1", content="hi", channel="web")
        events = [e async for e in orch.handle_streaming(msg)]
        done = events[-1]
        assert done.data["message_type"] == "text"
        assert done.data["payload"]["content"] == "reply"
        assert done.data["suggestions"] == []
        assert done.data["requires_confirmation"] is False
