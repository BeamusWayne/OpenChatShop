"""Re-audit cleanups for ``api/app.py`` (cluster: app).

These cover two cohesion cleanups that were copy-pasted across the customer
WebSocket / SSE handlers and are now factored into single helpers:

* ``_append_session_message`` — the append + bounded-history (``_msg_history_cap``)
  invariant, previously duplicated ~4x across the HUMAN_MODE / TRANSFER_PENDING /
  AI / assistant-response branches.
* ``_build_done_event`` — the ``done``-event reconstruction (rebuild AgentMessage,
  run the channel adapter, repackage), previously duplicated between the SSE and
  WebSocket paths.

The helpers are module-private closures inside ``create_app``, so these tests
drive them through the public endpoints (the real interaction), not by reaching
into internals — that also guards the *contract* the agent router relies on
(it reads the same shared ``_session_messages`` the WS writes).
"""
from __future__ import annotations

import os
from typing import Any
from unittest.mock import patch

from fastapi.testclient import TestClient

from open_chat_shop.core.types import AgentMessage, SessionMode, UserMessage

AGENT_SECRET = "agent-secret-123"

# Cap mirrors ``_msg_history_cap`` in app.py. If that constant changes the
# parity assertion below (trimmed length == cap) intentionally breaks so the
# bound stays a single source of truth.
_MSG_HISTORY_CAP = 200


class _RichOrchestrator:
    """Orchestrator stub that returns a RICH (order_card) reply.

    The rich payload deliberately has NO ``content`` key, so any reconstruction
    that dug ``text_fallback`` out of ``payload`` (instead of reading the
    explicit ``text_fallback``) would collapse it to "". Exposes only the
    surface ``create_app`` touches.
    """

    def __init__(self) -> None:
        self.received: list[UserMessage] = []
        self._handoff_queue = None
        self._context_manager = None

    async def handle_message(self, message: UserMessage) -> AgentMessage:
        self.received.append(message)
        return AgentMessage(
            message_type="order_card",
            payload={"order_id": "A123", "status": "shipped"},
            text_fallback="订单 A123 已发货",
            suggestions=["查看物流"],
            requires_confirmation=False,
        )


class _DowngradingOrchestrator:
    """Returns a ``product_list`` reply — web-supported, WeChat-UNsupported.

    Sending this over the ``wechat`` channel forces ``downgrade()``, whose
    payload is ``{"type": "text", "content": <text_fallback>}``. Because the
    rich payload carries NO ``content`` key, this is the scenario that catches a
    reconstruction reading the fallback from ``payload`` instead of the explicit
    ``text_fallback`` field: the downgraded body would render empty.
    """

    def __init__(self) -> None:
        self._handoff_queue = None
        self._context_manager = None

    async def handle_message(self, message: UserMessage) -> AgentMessage:
        return AgentMessage(
            message_type="product_list",
            payload={"items": [{"id": "p1"}, {"id": "p2"}]},
            text_fallback="找到 2 个商品",
        )


def _read_done(frame_iter: Any) -> dict[str, Any]:
    """Pull the first ``done`` frame's ``data`` from an iterator of dict frames."""
    for _ in range(10):
        frame = next(frame_iter)
        if frame.get("type") == "done":
            return dict(frame["data"])
    raise AssertionError("no 'done' frame observed")


# ---------------------------------------------------------------------------
# OPT 2 — done-event reconstruction parity (SSE vs WebSocket)
# ---------------------------------------------------------------------------


class TestDoneEventReconstructionParity:
    """SSE and WebSocket must produce byte-identical ``done`` payloads.

    Both paths now share ``_build_done_event``. The single-source guarantee is
    that, given the same streamed ``done`` event, both channels reconstruct the
    same adapted message — including carrying the explicit ``text_fallback``
    through for a rich type that has no ``payload["content"]``.
    """

    def _sse_done(self, client: TestClient) -> dict[str, Any]:
        import json

        with client.stream(
            "POST",
            "/api/v1/chat/stream",
            json={"session_id": "sse-1", "content": "我的订单", "channel": "web"},
        ) as resp:
            assert resp.status_code == 200
            for line in resp.iter_lines():
                if not line:
                    continue
                # Starlette TestClient yields str lines for SSE.
                text = line if isinstance(line, str) else line.decode()
                if not text.startswith("data: "):
                    continue
                event = json.loads(text[len("data: ") :])
                if event.get("type") == "done":
                    return dict(event["data"])
        raise AssertionError("no SSE 'done' event")

    def _ws_done(self, client: TestClient) -> dict[str, Any]:
        with client.websocket_connect("/ws/chat/ws-1?channel=web") as ws:
            ws.send_text("我的订单")

            def _frames() -> Any:
                while True:
                    yield ws.receive_json()

            return _read_done(_frames())

    def test_sse_and_ws_done_payloads_match(self) -> None:
        with patch.dict(os.environ, {"JWT_SECRET_KEY": "", "API_KEY": ""}):
            client = TestClient(create_app(orchestrator=_RichOrchestrator()))
            sse_data = self._sse_done(client)
            ws_data = self._ws_done(client)

        # The shared helper means both channels reconstruct identically.
        assert sse_data == ws_data
        # Rich type survives adaptation on the web channel (not downgraded).
        assert sse_data["message_type"] == "order_card"
        assert sse_data["payload"]["order_id"] == "A123"
        # suggestions / requires_confirmation are carried from the stream event.
        assert sse_data["suggestions"] == ["查看物流"]
        assert sse_data["requires_confirmation"] is False

    def test_downgrade_uses_explicit_text_fallback_not_payload(self) -> None:
        """A downgraded reply must render the explicit ``text_fallback``.

        Regression guard for the OPT-2 reconstruction: ``product_list`` is rich
        with NO ``payload["content"]`` and is unsupported by the WeChat channel,
        so the adapter downgrades to ``{"type": "text", "content": fallback}``.
        If ``_build_done_event`` regressed to sourcing the fallback from
        ``payload`` instead of the explicit field, this downgraded body would be
        empty. Verified on BOTH the SSE and WebSocket paths so the shared helper
        is pinned on each channel.
        """
        import json

        with patch.dict(os.environ, {"JWT_SECRET_KEY": "", "API_KEY": ""}):
            client = TestClient(create_app(orchestrator=_DowngradingOrchestrator()))

            # --- SSE path ---
            sse_done = None
            with client.stream(
                "POST",
                "/api/v1/chat/stream",
                json={
                    "session_id": "sse-wc",
                    "content": "看看商品",
                    "channel": "wechat",
                },
            ) as resp:
                for line in resp.iter_lines():
                    text = line if isinstance(line, str) else (line or b"").decode()
                    if text.startswith("data: "):
                        ev = json.loads(text[len("data: ") :])
                        if ev.get("type") == "done":
                            sse_done = ev["data"]
                            break

            # --- WebSocket path ---
            with client.websocket_connect("/ws/chat/ws-wc?channel=wechat") as ws:
                ws.send_text("看看商品")

                def _frames() -> Any:
                    while True:
                        yield ws.receive_json()

                ws_done = _read_done(_frames())

        for done in (sse_done, ws_done):
            assert done is not None
            # Downgraded to plain text on WeChat (unsupported rich type).
            assert done["message_type"] == "text"
            # The explicit text_fallback is the visible body — NOT "" from a
            # missing payload["content"].
            assert done["payload"]["content"] == "找到 2 个商品"
        # Both channels produce the same downgraded reconstruction.
        assert sse_done == ws_done


# ---------------------------------------------------------------------------
# OPT 1 — bounded session-history invariant (shared by the agent router)
# ---------------------------------------------------------------------------


class _PendingTransferContextManager:
    """Context manager whose sessions are all in TRANSFER_PENDING.

    Driving the WS in TRANSFER_PENDING means each inbound message is appended to
    history WITHOUT an orchestrator round-trip, so we can flood the cap quickly
    and deterministically through the same ``_append_session_message`` helper the
    AI/assistant branches use.
    """

    def __init__(self) -> None:
        self._ctx: dict[str, Any] = {}

    def get(self, session_id: str) -> Any:
        return self._ctx.get(session_id)


class _Ctx:
    def __init__(self) -> None:
        self.mode = SessionMode.TRANSFER_PENDING
        self.human_agent_id: str | None = None


class _PendingOrchestrator:
    """Orchestrator whose context_manager pins sessions to TRANSFER_PENDING.

    Also exposes a real ``_handoff_queue`` so the agent router (which reads the
    shared ``_session_messages``) is mounted — letting us verify the WS-written,
    cap-trimmed history through the public ``/api/v1/agent/history`` endpoint.
    """

    def __init__(self) -> None:
        from open_chat_shop.core.handoff import HandoffQueue

        self._handoff_queue = HandoffQueue()
        self._cm = _PendingTransferContextManager()
        self._context_manager = self._cm

    async def handle_message(self, message: UserMessage) -> AgentMessage:  # pragma: no cover
        raise AssertionError("TRANSFER_PENDING must not reach the orchestrator")

    def pin_pending(self, session_id: str) -> None:
        self._cm._ctx[session_id] = _Ctx()


class TestSessionHistoryCapInvariant:
    """Flooding the WS past the cap keeps only the newest ``_msg_history_cap``."""

    def test_history_trimmed_to_cap_keeps_newest(self) -> None:
        orch = _PendingOrchestrator()
        sid = "flood-sess"
        orch.pin_pending(sid)
        n = _MSG_HISTORY_CAP + 25  # comfortably over the cap

        with patch.dict(
            os.environ,
            {"JWT_SECRET_KEY": "", "API_KEY": "", "AGENT_SECRET": AGENT_SECRET},
        ):
            client = TestClient(create_app(orchestrator=orch))
            with client.websocket_connect(f"/ws/chat/{sid}") as ws:
                for i in range(n):
                    ws.send_text(f"msg-{i}")
                    # TRANSFER_PENDING replies with a transfer_status frame; drain
                    # it so the socket buffer stays in lockstep.
                    ws.receive_json()

            resp = client.get(
                f"/api/v1/agent/history/{sid}",
                headers={"X-Agent-Secret": AGENT_SECRET},
            )
            assert resp.status_code == 200
            messages = resp.json()["messages"]

        # Bounded to exactly the cap (not n) — the trim ran on the shared list.
        assert len(messages) == _MSG_HISTORY_CAP
        # Newest retained, oldest dropped (slice keeps the tail).
        assert messages[-1]["content"] == f"msg-{n - 1}"
        assert messages[0]["content"] == f"msg-{n - _MSG_HISTORY_CAP}"
        # The very first messages were evicted.
        contents = {m["content"] for m in messages}
        assert "msg-0" not in contents


# Imported late so patch.dict on os.environ is in effect before create_app reads
# JWT_SECRET_KEY / AGENT_SECRET (matches the other app tests' import placement).
from open_chat_shop.api.app import create_app  # noqa: E402
