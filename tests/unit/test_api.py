"""Unit tests for FastAPI application endpoints."""
from __future__ import annotations

from fastapi.testclient import TestClient

from open_chat_shop.api.app import create_app

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _StubOrchestrator:
    """Minimal async stub that returns a fixed AgentMessage."""

    def __init__(self, response_text: str = "pong") -> None:
        self._response_text = response_text
        self.last_message = None

    async def handle_message(self, message):
        self.last_message = message
        from open_chat_shop.core.types import AgentMessage

        return AgentMessage(
            message_type="text",
            payload={"content": self._response_text},
            text_fallback=self._response_text,
        )


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
    def test_health_returns_200(self) -> None:
        client = TestClient(create_app())
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_health_response_body(self) -> None:
        client = TestClient(create_app())
        resp = client.get("/health")
        body = resp.json()
        assert body["status"] == "ok"
        assert body["version"] == "0.1.0"


# ---------------------------------------------------------------------------
# Chat endpoint — without orchestrator
# ---------------------------------------------------------------------------


class TestChatNoOrchestrator:
    def test_chat_without_orchestrator_returns_503(self) -> None:
        client = TestClient(create_app(orchestrator=None))
        resp = client.post(
            "/api/v1/chat",
            json={
                "session_id": "s1",
                "content": "hello",
                "channel": "web",
            },
        )
        assert resp.status_code == 503


# ---------------------------------------------------------------------------
# Chat endpoint — with orchestrator
# ---------------------------------------------------------------------------


class TestChatWithOrchestrator:
    def setup_method(self) -> None:
        self.orchestrator = _StubOrchestrator(response_text="test reply")
        self.client = TestClient(create_app(orchestrator=self.orchestrator))

    def test_chat_returns_200(self) -> None:
        resp = self.client.post(
            "/api/v1/chat",
            json={
                "session_id": "s1",
                "content": "hello",
                "channel": "web",
            },
        )
        assert resp.status_code == 200

    def test_chat_response_fields(self) -> None:
        resp = self.client.post(
            "/api/v1/chat",
            json={
                "session_id": "s1",
                "content": "hello",
            },
        )
        body = resp.json()
        assert body["message_type"] == "text"
        assert body["text_fallback"] == "test reply"
        assert body["requires_confirmation"] is False

    def test_chat_passes_user_id(self) -> None:
        self.client.post(
            "/api/v1/chat",
            json={
                "session_id": "s1",
                "content": "hello",
                "user_id": "u-42",
            },
        )
        assert self.orchestrator.last_message.user_id == "u-42"

    def test_chat_default_channel_is_web(self) -> None:
        self.client.post(
            "/api/v1/chat",
            json={
                "session_id": "s1",
                "content": "hello",
            },
        )
        assert self.orchestrator.last_message.channel == "web"

    def test_chat_payload_contains_type(self) -> None:
        resp = self.client.post(
            "/api/v1/chat",
            json={
                "session_id": "s1",
                "content": "hello",
            },
        )
        body = resp.json()
        assert body["payload"]["type"] == "text"


# ---------------------------------------------------------------------------
# CORS headers
# ---------------------------------------------------------------------------


class TestCORS:
    def test_cors_headers_present_on_preflight(self) -> None:
        client = TestClient(create_app())
        resp = client.options(
            "/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
        # CORSMiddleware echoes the origin when allow_origins=["*"]
        assert "access-control-allow-origin" in resp.headers
        assert "GET" in resp.headers.get("access-control-allow-methods", "")
