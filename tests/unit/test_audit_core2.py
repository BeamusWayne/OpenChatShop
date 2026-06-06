"""Audit remediation regression tests — cluster CORE2 (api/app.py).

Covers two verified findings:

1. [CRITICAL — WS identity residual] The customer WebSocket entry
   ``/ws/chat/{session_id}`` bypasses ``AuthMiddleware`` and verifies the JWT
   itself. The residual bug: when a JWT secret IS configured but the presented
   token is invalid/expired/absent, the old code fell back to the
   client-supplied ``?user_id`` (``verified or user_id``), letting an attacker
   impersonate ANY user just by sending a bad token — the exact IDOR the REST
   entry already refuses (AuthMiddleware returns 401 before the handler runs).
   The fix: when a secret is configured, identity comes ONLY from the verified
   token; the client ``?user_id`` is honoured (advisory) ONLY when no secret is
   configured.

2. [MEDIUM — fire-and-forget WS sends] Handoff callbacks scheduled WS sends
   with ``get_event_loop().create_task(...)`` and never stored the task, so the
   loop kept only a weak reference and the customer/agent notification could be
   garbage-collected mid-send. The fix routes every send through
   ``_schedule_ws_send`` which uses ``get_running_loop`` and parks the task in
   ``_background_tasks`` (strong ref) with a done-callback that discards it and
   logs failures instead of swallowing them. These tests pin that the customer
   "agent connected" notification is actually delivered when a transfer is
   assigned.
"""
from __future__ import annotations

import os
from typing import Any
from unittest.mock import patch

from fastapi.testclient import TestClient
from jose import jwt as jose_jwt

from open_chat_shop.api.app import create_app
from open_chat_shop.core.context import InMemoryContextManager
from open_chat_shop.core.handoff import HandoffQueue, TransferRequest
from open_chat_shop.core.intent import CascadeIntentEngine, RuleBasedMatcher
from open_chat_shop.core.orchestrator import DialogueOrchestrator
from open_chat_shop.core.security import SecurityGuard
from open_chat_shop.core.strategy import RuleBasedStrategy
from open_chat_shop.core.tool import ToolInjector
from open_chat_shop.core.types import AgentMessage, UserMessage


def _make_jwt_token(payload: dict, secret: str) -> str:
    return jose_jwt.encode(payload, secret, algorithm="HS256")


class _CapturingOrchestrator:
    """Minimal orchestrator stub recording the messages it receives."""

    def __init__(self) -> None:
        self.received: list[UserMessage] = []
        self._handoff_queue = None
        self._context_manager = None

    async def handle_message(self, message: UserMessage) -> AgentMessage:
        self.received.append(message)
        return AgentMessage(
            message_type="text",
            payload={"content": "ok"},
            text_fallback="ok",
        )


def _drain_until_done(websocket: Any) -> None:
    for _ in range(10):
        frame = websocket.receive_json()
        if frame.get("type") == "done":
            return
    raise AssertionError("did not receive 'done' event from WebSocket")


# ---------------------------------------------------------------------------
# Finding 1 — WS identity residual (do not honour client user_id on bad token)
# ---------------------------------------------------------------------------


class TestWebSocketIdentityResidual:
    def test_invalid_token_with_secret_does_not_honor_client_user_id(self) -> None:
        """Secret configured + INVALID token + ?user_id=victim -> no identity.

        Regression: the old ``verified or user_id`` fallback would bind
        ``user_id == "victim"`` here, allowing impersonation with a forged
        token. With a secret configured, a bad token must yield ``None``.
        """
        orch = _CapturingOrchestrator()
        with patch.dict(os.environ, {"JWT_SECRET_KEY": "test-secret", "API_KEY": ""}):
            # Token signed with the WRONG secret -> JWTError on verify.
            bad_token = _make_jwt_token({"sub": "alice"}, "attacker-secret")
            client = TestClient(create_app(orchestrator=orch))
            with client.websocket_connect(
                f"/ws/chat/sess-bad?token={bad_token}&user_id=victim"
            ) as ws:
                ws.send_text("把别人的订单退款")
                _drain_until_done(ws)

        assert len(orch.received) == 1
        assert orch.received[0].user_id is None
        assert orch.received[0].user_id != "victim"

    def test_absent_token_with_secret_does_not_honor_client_user_id(self) -> None:
        """Secret configured + NO token + ?user_id=victim -> no identity.

        Same impersonation gap via simply omitting the token. With a secret
        configured the client ``?user_id`` must never be honoured.
        """
        orch = _CapturingOrchestrator()
        with patch.dict(os.environ, {"JWT_SECRET_KEY": "test-secret", "API_KEY": ""}):
            client = TestClient(create_app(orchestrator=orch))
            with client.websocket_connect(
                "/ws/chat/sess-notok?user_id=victim"
            ) as ws:
                ws.send_text("我是谁")
                _drain_until_done(ws)

        assert len(orch.received) == 1
        assert orch.received[0].user_id is None

    def test_valid_token_still_binds_sub_over_client_user_id(self) -> None:
        """Positive control: a valid token still wins over a spoofed user_id."""
        orch = _CapturingOrchestrator()
        with patch.dict(os.environ, {"JWT_SECRET_KEY": "test-secret", "API_KEY": ""}):
            token = _make_jwt_token({"sub": "alice"}, "test-secret")
            client = TestClient(create_app(orchestrator=orch))
            with client.websocket_connect(
                f"/ws/chat/sess-ok?token={token}&user_id=victim"
            ) as ws:
                ws.send_text("查我的订单")
                _drain_until_done(ws)

        assert len(orch.received) == 1
        assert orch.received[0].user_id == "alice"

    def test_no_secret_still_honors_advisory_client_user_id(self) -> None:
        """No secret configured -> the advisory client ?user_id IS used.

        Pins the other half of the contract: the impersonation tightening must
        NOT regress the fail-open-when-auth-disabled dev path, where the client
        ``?user_id`` is accepted as advisory identity.
        """
        orch = _CapturingOrchestrator()
        with patch.dict(os.environ, {"JWT_SECRET_KEY": "", "API_KEY": ""}):
            client = TestClient(create_app(orchestrator=orch))
            with client.websocket_connect(
                "/ws/chat/sess-dev?user_id=dev-user"
            ) as ws:
                ws.send_text("你好")
                _drain_until_done(ws)

        assert len(orch.received) == 1
        assert orch.received[0].user_id == "dev-user"


# ---------------------------------------------------------------------------
# Finding 2 — fire-and-forget WS sends must actually be delivered (not GC-dropped)
# ---------------------------------------------------------------------------


def _build_handoff_app() -> tuple[TestClient, HandoffQueue]:
    handoff_queue = HandoffQueue()
    orchestrator = DialogueOrchestrator(
        security_guard=SecurityGuard({}),
        context_manager=InMemoryContextManager(),
        intent_engine=CascadeIntentEngine(RuleBasedMatcher()),
        tool_injector=ToolInjector(registry={}, routing_rules=[]),
        strategy=RuleBasedStrategy(),
    )
    orchestrator.set_handoff_queue(handoff_queue)
    # Ensure no AGENT_SECRET leaks in from the environment for these tests.
    with patch.dict(os.environ, {"AGENT_SECRET": ""}):
        app = create_app(orchestrator)
    return TestClient(app), handoff_queue


class TestHandoffNotificationDelivery:
    def test_customer_receives_connected_notification_on_assign(self) -> None:
        """Assigning a transfer delivers the 'connected' frame to the customer.

        The assign callback schedules the customer notification through
        ``_schedule_ws_send`` (running loop + tracked task). Before the fix the
        bare ``get_event_loop().create_task`` task was unreferenced and could be
        GC-dropped; this asserts the notification arrives reliably.
        """
        client, handoff_queue = _build_handoff_app()
        session_id = "sess-assign"

        # Register an agent so assign() has someone to pick.
        reg = client.post("/api/v1/agent/register", json={"name": "客服X"}).json()
        agent_id = reg["agent_id"]

        # Queue a transfer for this session (accept() requires it to be queued).
        handoff_queue.enqueue(
            TransferRequest(
                request_id="tr-assign",
                session_id=session_id,
                user_id="user-assign",
                reason="转人工",
            )
        )

        with client.websocket_connect(f"/ws/agent/{agent_id}") as agent_ws:
            # Drain the initial queue_state frame the agent receives on connect.
            agent_ws.receive_json()
            with client.websocket_connect(f"/ws/chat/{session_id}") as cust_ws:
                # Accepting the session triggers assign -> _on_assign_cb ->
                # _schedule_ws_send(cust_ws, transfer_status/connected).
                resp = client.post(f"/api/v1/agent/accept/{session_id}")
                assert resp.status_code == 200

                # The customer must receive the 'connected' notification; if the
                # send task were GC-dropped this would hang/time out.
                frame = cust_ws.receive_json()
                assert frame["type"] == "transfer_status"
                assert frame["data"]["status"] == "connected"
                assert frame["data"]["agent_name"] == "客服X"
