"""WebSocket identity binding tests (audit CRITICAL-1 IDOR residual).

The customer WebSocket entry ``/ws/chat/{session_id}`` bypasses the HTTP
``AuthMiddleware``, so it must verify the JWT itself (from the ``?token=``
query parameter) and bind the server-verified ``sub`` claim as the
authoritative ``user_id`` on the constructed :class:`UserMessage`.

Why this matters: if the WebSocket trusted a client-supplied ``user_id``
(or carried no identity at all), an attacker could act as any user — the
exact Broken-Object-Level-Authorization gap the REST/SSE entries already
close by trusting the verified token ``sub`` over client input. These
tests pin that the WS entry now derives identity from the token, not the
client, and that it stays consistent with the REST fail-open-when-auth-
disabled posture (no token / no secret stays advisory, not rejected).
"""
from __future__ import annotations

import datetime
import os
from typing import Any
from unittest.mock import patch

from fastapi.testclient import TestClient
from jose import jwt as jose_jwt

from open_chat_shop.api.app import create_app
from open_chat_shop.core.types import AgentMessage, UserMessage


def _make_jwt_token(payload: dict, secret: str) -> str:
    """Create a signed JWT token for testing (matches test_auth.py)."""
    return jose_jwt.encode(payload, secret, algorithm="HS256")


class _CapturingOrchestrator:
    """Minimal orchestrator stub that records the messages it receives.

    Exposes only the surface ``app.py`` touches: ``handle_message`` plus the
    ``_handoff_queue`` / ``_context_manager`` attributes the factory reads.
    """

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
    """Read WS frames until the streaming 'done' event arrives."""
    for _ in range(10):
        frame = websocket.receive_json()
        if frame.get("type") == "done":
            return
    raise AssertionError("did not receive 'done' event from WebSocket")


class TestWebSocketIdentityBinding:
    """The verified JWT ``sub`` is the authoritative user_id on WS messages."""

    def test_valid_token_binds_user_id_from_sub(self) -> None:
        """A valid ?token= makes UserMessage.user_id equal the token's sub."""
        orch = _CapturingOrchestrator()
        with patch.dict(os.environ, {"JWT_SECRET_KEY": "test-secret", "API_KEY": ""}):
            token = _make_jwt_token({"sub": "alice"}, "test-secret")
            client = TestClient(create_app(orchestrator=orch))
            with client.websocket_connect(
                f"/ws/chat/sess-1?token={token}"
            ) as ws:
                ws.send_text("查一下我的订单")
                _drain_until_done(ws)

        assert len(orch.received) == 1
        # Authoritative identity comes from the server-verified token, not
        # from anything the client could place in the frame.
        assert orch.received[0].user_id == "alice"

    def test_client_supplied_user_id_does_not_override_token(self) -> None:
        """A spoofed ?user_id= is ignored; the token sub wins."""
        orch = _CapturingOrchestrator()
        with patch.dict(os.environ, {"JWT_SECRET_KEY": "test-secret", "API_KEY": ""}):
            token = _make_jwt_token({"sub": "alice"}, "test-secret")
            client = TestClient(create_app(orchestrator=orch))
            # Client tries to impersonate "victim" via the query param.
            with client.websocket_connect(
                f"/ws/chat/sess-2?token={token}&user_id=victim"
            ) as ws:
                ws.send_text("把别人的订单退款")
                _drain_until_done(ws)

        assert len(orch.received) == 1
        # Server-verified sub must override the spoofed client value.
        assert orch.received[0].user_id == "alice"
        assert orch.received[0].user_id != "victim"

    def test_invalid_token_with_spoofed_user_id_yields_no_identity(self) -> None:
        """The dangerous branch: JWT secret SET + garbage token + spoofed ?user_id=.

        This is the IDOR residual the existing 'spoofed user_id' test never
        exercised: it only sent a *valid* token. Here an attacker presents an
        unparseable token AND ?user_id=victim. ``_resolve_ws_identity`` returns
        None for the bad token, and because a secret is configured the handler
        MUST NOT fall back to the client-supplied id. So the bound identity is
        None (treated as unauthenticated by order-ownership tools), never
        'victim'. If the ``or user_id`` fallback ever returned, this asserts a
        full Broken-Object-Level-Authorization bypass on the customer WS.
        """
        orch = _CapturingOrchestrator()
        with patch.dict(os.environ, {"JWT_SECRET_KEY": "test-secret", "API_KEY": ""}):
            client = TestClient(create_app(orchestrator=orch))
            with client.websocket_connect(
                "/ws/chat/sess-bad?token=not.a.valid.jwt&user_id=victim"
            ) as ws:
                ws.send_text("把别人的订单退款")
                _drain_until_done(ws)

        assert len(orch.received) == 1
        # Invalid token must degrade to "no identity", NOT to the spoofed value.
        assert orch.received[0].user_id is None
        assert orch.received[0].user_id != "victim"

    def test_forged_signature_token_yields_no_identity(self) -> None:
        """A token signed with the WRONG secret must not authenticate.

        An attacker who controls the payload but not the server secret signs
        ``{"sub": "victim"}`` with their own key. Signature verification fails,
        so identity resolves to None — the forged ``sub`` is never trusted even
        though it is syntactically a valid JWT.
        """
        orch = _CapturingOrchestrator()
        with patch.dict(os.environ, {"JWT_SECRET_KEY": "real-secret", "API_KEY": ""}):
            forged = _make_jwt_token({"sub": "victim"}, "attacker-secret")
            client = TestClient(create_app(orchestrator=orch))
            with client.websocket_connect(
                f"/ws/chat/sess-forge?token={forged}&user_id=victim"
            ) as ws:
                ws.send_text("查别人的订单")
                _drain_until_done(ws)

        assert len(orch.received) == 1
        assert orch.received[0].user_id is None
        assert orch.received[0].user_id != "victim"

    def test_expired_token_with_spoofed_user_id_yields_no_identity(self) -> None:
        """An expired (but correctly-signed) token must not authenticate.

        The REST entry rejects an expired JWT with a 401 (test_auth.py). The WS
        entry bypasses AuthMiddleware, so it must reach the same conclusion
        itself: an expired token resolves to None and the spoofed ?user_id= is
        not honoured — otherwise expiry would silently degrade to client
        control of identity.
        """
        orch = _CapturingOrchestrator()
        with patch.dict(os.environ, {"JWT_SECRET_KEY": "test-secret", "API_KEY": ""}):
            expired_at = datetime.datetime.now(
                datetime.UTC
            ) - datetime.timedelta(hours=1)
            token = _make_jwt_token(
                {"sub": "alice", "exp": expired_at}, "test-secret"
            )
            client = TestClient(create_app(orchestrator=orch))
            with client.websocket_connect(
                f"/ws/chat/sess-exp?token={token}&user_id=victim"
            ) as ws:
                ws.send_text("查我的订单")
                _drain_until_done(ws)

        assert len(orch.received) == 1
        assert orch.received[0].user_id is None
        assert orch.received[0].user_id != "victim"

    def test_no_secret_configured_stays_advisory(self) -> None:
        """With auth disabled (no JWT secret), the connection is NOT rejected.

        This mirrors the REST entry's fail-open-when-auth-disabled behaviour:
        local/dev use without credentials keeps working in advisory mode
        rather than being tightened into a hard connection refusal.
        """
        orch = _CapturingOrchestrator()
        with patch.dict(os.environ, {"JWT_SECRET_KEY": "", "API_KEY": ""}):
            client = TestClient(create_app(orchestrator=orch))
            with client.websocket_connect("/ws/chat/sess-3") as ws:
                ws.send_text("你好")
                _drain_until_done(ws)

        # Reached the orchestrator (connection not refused); no authoritative
        # identity is bound when auth is disabled.
        assert len(orch.received) == 1
        assert orch.received[0].user_id is None
