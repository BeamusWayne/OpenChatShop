"""End-to-end tests for the OpenChatShop chat API.

Tests the full request path through FastAPI routing, middleware,
orchestrator, and channel adaptation -- using TestClient (ASGI in-process)
so no running server is required.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from open_chat_shop.api.app import create_app
from open_chat_shop.core.context import InMemoryContextManager
from open_chat_shop.core.handoff import HandoffQueue
from open_chat_shop.core.intent import CascadeIntentEngine, IntentInfo, RuleBasedMatcher
from open_chat_shop.core.orchestrator import DialogueOrchestrator
from open_chat_shop.core.security import SecurityGuard
from open_chat_shop.core.strategy import RuleBasedStrategy
from open_chat_shop.core.tool import ToolInjector

# ---------------------------------------------------------------------------
# Shared fixture helpers
# ---------------------------------------------------------------------------


def _build_orchestrator() -> DialogueOrchestrator:
    """Build a minimal DialogueOrchestrator suitable for E2E tests."""
    security = SecurityGuard({
        "rbac": {
            "roles": [
                {"name": "customer", "tools": ["query_order", "search_product"]},
            ]
        }
    })
    context = InMemoryContextManager()

    matcher = RuleBasedMatcher()
    matcher.add_rule("greeting", r"你好|您好|hi|hello")
    matcher.add_rule("query_order", r"订单|order|查询.*状态|查询订单")
    matcher.add_rule("search_product", r"搜索|查找|找.*商品")
    intent = CascadeIntentEngine(matcher)
    intent.register_intent(IntentInfo(
        name="greeting",
        display_name="问候",
        description="用户打招呼",
        sample_count=5,
    ))
    intent.register_intent(IntentInfo(
        name="query_order",
        display_name="查询订单",
        description="查询订单状态",
        sample_count=10,
    ))

    tools = ToolInjector(registry={}, routing_rules=[], max_tools_per_turn=3)
    strategy = RuleBasedStrategy()

    orchestrator = DialogueOrchestrator(
        security_guard=security,
        context_manager=context,
        intent_engine=intent,
        tool_injector=tools,
        strategy=strategy,
    )
    return orchestrator


@pytest.fixture()
def client() -> TestClient:
    """TestClient wired with a fully-functional orchestrator + handoff queue."""
    orchestrator = _build_orchestrator()
    handoff_queue = HandoffQueue()
    orchestrator.set_handoff_queue(handoff_queue)

    app = create_app(orchestrator)
    return TestClient(app)


# ---------------------------------------------------------------------------
# Test 1: Health check
# ---------------------------------------------------------------------------


class TestHealthCheck:
    """GET /health must return status=ok with version info."""

    def test_health_returns_200_ok(self, client: TestClient) -> None:
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert "version" in body

    def test_health_ready_returns_check_details(self, client: TestClient) -> None:
        resp = client.get("/health/ready")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert "checks" in body
        assert "uptime_seconds" in body


# ---------------------------------------------------------------------------
# Test 2: REST chat endpoint
# ---------------------------------------------------------------------------


class TestChatEndpoint:
    """POST /api/v1/chat -- request/response contract validation."""

    def test_greeting_returns_valid_response(self, client: TestClient) -> None:
        resp = client.post("/api/v1/chat", json={
            "session_id": "e2e-test-1",
            "content": "你好",
            "channel": "web",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert "message_type" in body
        assert "payload" in body
        assert "text_fallback" in body
        assert isinstance(body["payload"], dict)
        assert isinstance(body["text_fallback"], str)
        assert len(body["text_fallback"]) > 0

    def test_query_order_returns_order_content(self, client: TestClient) -> None:
        resp = client.post("/api/v1/chat", json={
            "session_id": "e2e-test-1",
            "content": "查询订单",
            "channel": "web",
        })
        assert resp.status_code == 200
        body = resp.json()
        text = body["text_fallback"]
        # RuleBasedStrategy returns a clarify prompt when order_id is missing
        assert "订单" in text or "order" in text.lower()

    def test_conversation_stays_in_same_session(self, client: TestClient) -> None:
        """Second message within the same session_id maintains context."""
        resp1 = client.post("/api/v1/chat", json={
            "session_id": "e2e-session-ctx",
            "content": "你好",
            "channel": "web",
        })
        assert resp1.status_code == 200

        resp2 = client.post("/api/v1/chat", json={
            "session_id": "e2e-session-ctx",
            "content": "查询订单",
            "channel": "web",
        })
        assert resp2.status_code == 200
        body = resp2.json()
        assert "text_fallback" in body

    def test_invalid_content_rejected(self, client: TestClient) -> None:
        """Empty content should fail validation."""
        resp = client.post("/api/v1/chat", json={
            "session_id": "e2e-test-invalid",
            "content": "",
            "channel": "web",
        })
        assert resp.status_code == 422

    def test_missing_session_id_rejected(self, client: TestClient) -> None:
        """Missing session_id should fail validation."""
        resp = client.post("/api/v1/chat", json={
            "content": "你好",
            "channel": "web",
        })
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Test 3: SSE streaming
# ---------------------------------------------------------------------------


class TestSSEStreaming:
    """GET /api/v1/chat/stream -- Server-Sent Events validation."""

    def test_stream_returns_sse_events(self, client: TestClient) -> None:
        resp = client.get("/api/v1/chat/stream", params={
            "session_id": "e2e-stream-1",
            "content": "你好",
            "channel": "web",
        })
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "text/event-stream; charset=utf-8"

        raw = resp.text
        # SSE frames are "data: ...\n\n" sequences
        assert "data: " in raw

        # Parse individual SSE events
        events = [
            line[len("data: "):]
            for line in raw.split("\n")
            if line.startswith("data: ")
        ]
        assert len(events) >= 2  # At minimum: typing + done

        # First event should be typing indicator
        first = json.loads(events[0])
        assert first["type"] == "typing"
        assert first["data"]["status"] == "thinking"

        # Last event should be done
        last = json.loads(events[-1])
        assert last["type"] == "done"
        assert "message_type" in last["data"]

    def test_stream_yields_chunk_content(self, client: TestClient) -> None:
        """Non-LLM path: single chunk event with full text content."""
        resp = client.get("/api/v1/chat/stream", params={
            "session_id": "e2e-stream-2",
            "content": "你好",
            "channel": "web",
        })
        assert resp.status_code == 200

        events = [
            line[len("data: "):]
            for line in resp.text.split("\n")
            if line.startswith("data: ")
        ]
        # Filter chunk events
        chunk_events = [
            json.loads(e) for e in events
            if json.loads(e)["type"] == "chunk"
        ]
        assert len(chunk_events) >= 1
        assert "content_delta" in chunk_events[0]["data"]
        assert len(chunk_events[0]["data"]["content_delta"]) > 0

    def test_stream_missing_params_rejected(self, client: TestClient) -> None:
        """Missing required query params should fail validation."""
        resp = client.get("/api/v1/chat/stream", params={
            "session_id": "e2e-stream-missing",
        })
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Test 4: Agent registration + queue
# ---------------------------------------------------------------------------


class TestAgentRegistrationAndQueue:
    """Agent API: register, list, queue flow."""

    def test_register_returns_agent_id(self, client: TestClient) -> None:
        resp = client.post("/api/v1/agent/register", json={
            "name": "E2E Test Agent",
            "department": "test",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["agent_id"].startswith("agent-")
        assert body["name"] == "E2E Test Agent"
        assert body["department"] == "test"

    def test_registered_agent_appears_in_list(self, client: TestClient) -> None:
        # Register
        reg_resp = client.post("/api/v1/agent/register", json={
            "name": "E2E List Agent",
            "department": "support",
        })
        assert reg_resp.status_code == 200
        agent_id = reg_resp.json()["agent_id"]

        # List
        list_resp = client.get("/api/v1/agent/agents")
        assert list_resp.status_code == 200
        agents = list_resp.json()
        assert len(agents) >= 1

        # Find our agent
        found = next(
            (a for a in agents if a["agent_id"] == agent_id),
            None,
        )
        assert found is not None
        assert found["name"] == "E2E List Agent"
        assert found["department"] == "support"
        assert found["status"] == "online"

    def test_empty_queue_initially(self, client: TestClient) -> None:
        resp = client.get("/api/v1/agent/queue")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_empty_active_initially(self, client: TestClient) -> None:
        resp = client.get("/api/v1/agent/active")
        assert resp.status_code == 200
        assert resp.json() == []
