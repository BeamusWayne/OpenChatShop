"""Tests for auth middleware public paths and WebSocket agent token validation."""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any
from unittest.mock import patch

from fastapi.testclient import TestClient

from open_chat_shop.api.app import create_app
from open_chat_shop.core.context import InMemoryContextManager
from open_chat_shop.core.handoff import HandoffQueue
from open_chat_shop.core.intent import CascadeIntentEngine, RuleBasedMatcher
from open_chat_shop.core.orchestrator import DialogueOrchestrator
from open_chat_shop.core.security import SecurityGuard
from open_chat_shop.core.strategy import RuleBasedStrategy
from open_chat_shop.core.tool import ToolInjector


class TestPublicPaths:
    """Verify health/metrics endpoints are accessible without auth."""

    @patch.dict(os.environ, {"JWT_SECRET_KEY": "test-secret", "API_KEY": ""})
    def test_health_accessible_without_auth(self):
        client = TestClient(create_app())
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    @patch.dict(os.environ, {"JWT_SECRET_KEY": "test-secret", "API_KEY": ""})
    def test_health_ready_accessible_without_auth(self):
        client = TestClient(create_app())
        resp = client.get("/health/ready")
        assert resp.status_code == 200

    @patch.dict(os.environ, {"JWT_SECRET_KEY": "test-secret", "API_KEY": ""})
    def test_metrics_accessible_without_auth(self):
        client = TestClient(create_app())
        resp = client.get("/metrics")
        assert resp.status_code != 401

    @patch.dict(os.environ, {"JWT_SECRET_KEY": "test-secret", "API_KEY": ""})
    def test_chat_requires_auth(self):
        client = TestClient(create_app())
        resp = client.post(
            "/api/v1/chat",
            json={"session_id": "s1", "content": "hello"},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Agent WebSocket token gate
# ---------------------------------------------------------------------------
# The previous version of these tests was @pytest.mark.skip'd with the reason
# "Sync TestClient blocks on WS...". Two facts made the skips both real AND
# misleading:
#   1) The agent WS sends its first ``queue_state`` frame ONLY when the app has
#      a handoff queue (create_app derives it from the orchestrator). The old
#      tests called create_app(agent_token=...) with NO orchestrator, so no
#      queue_state was ever sent — the accept-case assertion could never pass.
#   2) Starlette's *sync* TestClient portal does deadlock on this WS in-process,
#      so the suggested "port to TestClient.websocket_connect" pattern hangs.
# The robust fix is to drive the ASGI app's WebSocket protocol directly (no
# thread portal). ``_AgentWS`` below speaks raw ASGI websocket events, which is
# deterministic and lets us assert the accept/reject/close-code outcomes of the
# token gate at src/open_chat_shop/api/app.py (``if agent_token: ... close(4001)``).


def _build_orchestrator() -> DialogueOrchestrator:
    """Orchestrator wired with a handoff queue so the agent WS emits queue_state."""
    orchestrator = DialogueOrchestrator(
        security_guard=SecurityGuard({}),
        context_manager=InMemoryContextManager(),
        intent_engine=CascadeIntentEngine(RuleBasedMatcher()),
        tool_injector=ToolInjector(registry={}, routing_rules=[]),
        strategy=RuleBasedStrategy(),
    )
    orchestrator.set_handoff_queue(HandoffQueue())
    return orchestrator


class _AgentWS:
    """Minimal in-process ASGI WebSocket client for the agent endpoint.

    Avoids the sync ``TestClient`` thread portal (which deadlocks on this WS)
    by exchanging raw ASGI ``websocket.*`` events with the app coroutine on the
    current event loop. Records whether the server accepted and, if it closed,
    the close code (4001 is the token-gate rejection).
    """

    def __init__(self, app: Any, path: str, query: str = "") -> None:
        self._app = app
        self._scope = {
            "type": "websocket",
            "path": path,
            "raw_path": path.encode(),
            "query_string": query.encode(),
            "headers": [(b"host", b"testserver")],
            "subprotocols": [],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
            "scheme": "ws",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
        }
        self._to_app: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._from_app: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._task: asyncio.Future[Any] | None = None
        self.accepted = False
        self.close_code: int | None = None

    async def _receive(self) -> dict[str, Any]:
        return await self._to_app.get()

    async def _send(self, message: dict[str, Any]) -> None:
        await self._from_app.put(message)

    async def __aenter__(self) -> _AgentWS:
        self._task = asyncio.ensure_future(
            self._app(self._scope, self._receive, self._send)
        )
        await self._to_app.put({"type": "websocket.connect"})
        message = await asyncio.wait_for(self._from_app.get(), timeout=5)
        if message["type"] == "websocket.accept":
            self.accepted = True
        elif message["type"] == "websocket.close":
            self.close_code = message.get("code")
        return self

    async def receive_json(self) -> dict[str, Any] | None:
        message = await asyncio.wait_for(self._from_app.get(), timeout=5)
        if message["type"] == "websocket.close":
            self.close_code = message.get("code")
            return None
        return json.loads(message.get("text", "null"))

    async def __aexit__(self, *exc: Any) -> None:
        await self._to_app.put({"type": "websocket.disconnect", "code": 1000})
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=5)
            except (TimeoutError, asyncio.CancelledError):
                self._task.cancel()


class TestAgentWebSocketToken:
    """Verify the agent WebSocket validates AGENT_TOKEN when configured.

    These tests were previously skipped, leaving the security-critical token
    gate (close 4001 on a bad token) with zero executing coverage.
    """

    async def test_ws_agent_no_token_required_when_not_configured(self) -> None:
        """No agent_token configured: connection is accepted, queue_state sent."""
        app = create_app(_build_orchestrator(), agent_token=None)
        async with _AgentWS(app, "/ws/agent/agent-test", "name=Test") as ws:
            assert ws.accepted is True
            frame = await ws.receive_json()
            assert frame is not None
            assert frame["type"] == "queue_state"

    async def test_ws_agent_rejects_wrong_token(self) -> None:
        """A wrong ?token= is rejected: never accepted, closed with code 4001."""
        app = create_app(_build_orchestrator(), agent_token="correct-secret")
        async with _AgentWS(app, "/ws/agent/agent-test", "token=wrong") as ws:
            # The gate must close BEFORE accept — a regression that inverted the
            # comparison or dropped the close() would accept the attacker here.
            assert ws.accepted is False
            assert ws.close_code == 4001

    async def test_ws_agent_accepts_correct_token(self) -> None:
        """The correct ?token= is accepted and receives the queue_state frame."""
        app = create_app(_build_orchestrator(), agent_token="correct-secret")
        async with _AgentWS(
            app, "/ws/agent/agent-test", "token=correct-secret&name=Test"
        ) as ws:
            assert ws.accepted is True
            frame = await ws.receive_json()
            assert frame is not None
            assert frame["type"] == "queue_state"

    async def test_ws_agent_missing_token_rejected_when_configured(self) -> None:
        """A configured gate also rejects a connection with NO ?token= at all.

        ``query_params.get("token", "")`` yields "" which != the secret, so the
        empty/absent token must be closed with 4001 just like a wrong one.
        """
        app = create_app(_build_orchestrator(), agent_token="correct-secret")
        async with _AgentWS(app, "/ws/agent/agent-test", "name=Test") as ws:
            assert ws.accepted is False
            assert ws.close_code == 4001
