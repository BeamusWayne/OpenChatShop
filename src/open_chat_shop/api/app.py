"""FastAPI application — REST + WebSocket endpoints."""
from __future__ import annotations

import asyncio
import hmac
import importlib.metadata
import json
import logging
import os
from collections.abc import AsyncIterator, Callable
from typing import Any, cast

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from jose import JWTError
from jose import jwt as jose_jwt
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware as _BaseMiddleware
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response as StarletteResponse
from starlette.types import ASGIApp

from open_chat_shop.api.agent import create_agent_router
from open_chat_shop.api.auth import AuthMiddleware
from open_chat_shop.api.streaming import StreamEvent, StreamingOrchestrator
from open_chat_shop.api.wechat import setup_wechat_routes
from open_chat_shop.channel.registry import default_registry
from open_chat_shop.core.handoff import HumanAgent, TransferRequest
from open_chat_shop.core.orchestrator import DialogueOrchestrator
from open_chat_shop.core.types import AgentMessage, SessionMode, UserMessage

logger = logging.getLogger(__name__)

try:
    _VERSION = importlib.metadata.version("open-chat-shop")
except importlib.metadata.PackageNotFoundError:
    _VERSION = "0.1.0"


def _resolve_ws_identity(token: str | None, jwt_secret: str | None) -> str | None:
    """Return the server-verified ``sub`` for a customer WebSocket, else ``None``.

    The WebSocket entry bypasses the HTTP ``AuthMiddleware``, so it must verify
    the JWT itself (same jose/HS256/JWT_SECRET_KEY as the middleware). Returns
    the token's ``sub`` only when ``jwt_secret`` is set AND the token is present
    and valid; otherwise returns ``None``.

    The caller decides what ``None`` means: when a secret is configured it MUST
    treat ``None`` as "no identity" and never fall back to a client-supplied
    ``user_id`` (an invalid/expired token must not let a caller impersonate
    another user — the REST entry refuses this with a 401). Only when no secret
    is configured does the caller accept the advisory client ``user_id``.
    """
    if not jwt_secret or not token:
        return None
    try:
        claims = jose_jwt.decode(token, jwt_secret, algorithms=["HS256"])
    except JWTError:
        logger.warning("WebSocket JWT validation failed")
        return None
    sub = claims.get("sub")
    return sub if isinstance(sub, str) and sub else None


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    session_id: str = Field(..., max_length=128)
    content: str = Field(..., min_length=1, max_length=2000)
    channel: str = Field("web", max_length=32)
    user_id: str | None = Field(None, max_length=128)


class ChatResponse(BaseModel):
    message_type: str
    payload: dict[str, Any]
    text_fallback: str
    suggestions: list[str] = []
    requires_confirmation: bool = False


class HealthResponse(BaseModel):
    status: str
    version: str


class CheckDetail(BaseModel):
    status: str
    latency_ms: float | None = None
    error: str | None = None


class ReadyResponse(BaseModel):
    status: str
    version: str
    checks: dict[str, CheckDetail]
    uptime_seconds: float


# ---------------------------------------------------------------------------
# Security headers middleware
# ---------------------------------------------------------------------------


class SecurityHeadersMiddleware(_BaseMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> StarletteResponse:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        csp = (
            "default-src 'self'; script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'"
        )
        if request.url.path in ("/docs", "/redoc"):
            csp = (
                "default-src 'self' cdn.jsdelivr.net unpkg.com; "
                "script-src 'self' 'unsafe-inline' cdn.jsdelivr.net unpkg.com; "
                "style-src 'self' 'unsafe-inline' cdn.jsdelivr.net unpkg.com"
            )
        response.headers["Content-Security-Policy"] = csp
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
        return response


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------


def create_app(
    orchestrator: DialogueOrchestrator | None = None,
    lifespan: Callable[..., Any] | None = None,
    agent_token: str | None = None,
) -> FastAPI:
    """Build and return a configured FastAPI application.

    *orchestrator* may be ``None`` — in that case chat endpoints return 503,
    but /health still works.

    *lifespan* is an optional async context manager for startup/shutdown hooks,
    as supported by FastAPI's ``lifespan`` parameter.
    """
    app = FastAPI(
        title="OpenChatShop API",
        version=_VERSION,
        description="E-commerce intelligent dialogue system",
        lifespan=lifespan,
    )

    cors_origins = os.environ.get(
        "CORS_ORIGINS",
        "http://localhost:3000,http://localhost:8000",
    ).split(",")

    deploy_env = os.environ.get("DEPLOY_ENV", "development")
    if deploy_env == "production" and not os.environ.get("CORS_ORIGINS"):
        logger.warning(
            "CORS_ORIGINS not set in production — using localhost defaults. "
            "Set CORS_ORIGINS to your actual domain(s)."
        )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_middleware(SecurityHeadersMiddleware)

    # Auth middleware (reads JWT_SECRET_KEY and optionally API_KEY from env)
    jwt_secret = os.environ.get("JWT_SECRET_KEY", "")
    api_key = os.environ.get("API_KEY", "")
    app.add_middleware(
        AuthMiddleware,
        jwt_secret=jwt_secret or None,
        api_key=api_key or None,
    )

    _registry = default_registry()
    _orchestrator = orchestrator
    import time as _time

    _start_time: float = _time.monotonic()

    # Shared state for WebSocket tracking and session message history
    _agent_sockets: dict[str, WebSocket] = {}
    _customer_sockets: dict[str, WebSocket] = {}
    _session_messages: dict[str, list[dict[str, Any]]] = {}

    # Expose socket dicts for graceful shutdown via app.state
    app.state.agent_sockets = _agent_sockets
    app.state.customer_sockets = _customer_sockets
    _session_modes: dict[str, SessionMode] = {}
    _background_tasks: set[asyncio.Task[None]] = set()

    _msg_history_cap = 200

    async def _delayed_session_cleanup(sid: str, delay: float = 300.0) -> None:
        """Remove session message history after *delay* seconds.

        Preserves messages long enough for agent dashboard to fetch history
        after the customer disconnects.
        """
        await asyncio.sleep(delay)
        _session_messages.pop(sid, None)

    def _append_session_message(sid: str, entry: dict[str, Any]) -> None:
        """Append *entry* to a session's history, trimming to the cap.

        Single owner of the append + bounded-list invariant that was
        copy-pasted across the customer WebSocket branches (user message in
        HUMAN_MODE / TRANSFER_PENDING / AI path, and the assistant response).
        Keeping it in one place means the ``_msg_history_cap`` bound cannot
        drift between branches.
        """
        msgs = _session_messages.setdefault(sid, [])
        msgs.append(entry)
        if len(msgs) > _msg_history_cap:
            _session_messages[sid] = msgs[-_msg_history_cap:]

    def _build_done_event(
        event: StreamEvent, adapter: Any
    ) -> StreamEvent:
        """Reconstruct the channel-adapted ``done`` event from a stream event.

        The SSE and WebSocket paths both rebuild an :class:`AgentMessage` from
        the streaming ``done`` payload, run it through the channel *adapter*,
        and repackage the adapted result as a ``done`` event. The only thing
        that differs between the two paths is the adapter instance and the wire
        encoding (``to_sse`` vs ``to_json``), so the shared reconstruction lives
        here and the caller picks the encoding.

        ``text_fallback`` is read explicitly (not dug out of ``payload``)
        because rich payloads (order_card, product_list, ...) have no
        ``content`` key — see streaming.py's done event.
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
                "requires_confirmation": event.data.get(
                    "requires_confirmation", False
                ),
            },
        )

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(status="ok", version=_VERSION)

    # ------------------------------------------------------------------
    # Readiness probe
    # ------------------------------------------------------------------

    async def _check_database(app_ref: FastAPI) -> CheckDetail:
        engine = getattr(app_ref.state, "db_engine", None)
        if engine is None:
            return CheckDetail(status="ok", latency_ms=0)
        try:
            import time

            from sqlalchemy import text
            t0 = time.monotonic()
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return CheckDetail(
                status="ok", latency_ms=round((time.monotonic() - t0) * 1000, 1)
            )
        except Exception as exc:
            return CheckDetail(status="unhealthy", error=str(exc))

    async def _check_redis(app_ref: FastAPI) -> CheckDetail:
        client = getattr(app_ref.state, "redis_client", None)
        if client is None:
            return CheckDetail(status="ok", latency_ms=0)
        try:
            import time
            t0 = time.monotonic()
            await client.ping()
            return CheckDetail(
                status="ok", latency_ms=round((time.monotonic() - t0) * 1000, 1)
            )
        except Exception as exc:
            return CheckDetail(status="unhealthy", error=str(exc))

    @app.get("/health/ready", response_model=ReadyResponse)
    async def readiness() -> ReadyResponse:
        import time

        checks: dict[str, CheckDetail] = {}
        checks["database"] = await _check_database(app)
        checks["redis"] = await _check_redis(app)

        overall = "ok"
        for detail in checks.values():
            if detail.status == "unhealthy":
                overall = "unhealthy"
                break

        uptime = time.monotonic() - _start_time

        resp = ReadyResponse(
            status=overall,
            version=_VERSION,
            checks=checks,
            uptime_seconds=round(uptime, 1),
        )

        if overall == "unhealthy":
            raise HTTPException(status_code=503, detail=resp.model_dump())
        return resp

    # ------------------------------------------------------------------
    # REST chat
    # ------------------------------------------------------------------

    @app.post("/api/v1/chat", response_model=ChatResponse)
    async def chat(request: ChatRequest, http_request: Request) -> ChatResponse:
        if _orchestrator is None:
            raise HTTPException(status_code=503, detail="Service not configured")

        # Session mode guard: reject when in human service mode
        _s_mode = _session_modes.get(request.session_id)
        if _s_mode == SessionMode.HUMAN_MODE:
            raise HTTPException(
                status_code=423,
                detail="Session in human service mode",
            )
        if _context_manager is not None:
            ctx = _context_manager.get(request.session_id)
            if ctx is not None and ctx.mode == SessionMode.HUMAN_MODE:
                raise HTTPException(
                    status_code=423,
                    detail="Session in human service mode",
                )

        # Trust the server-verified identity (JWT sub bound by AuthMiddleware)
        # over any client-supplied user_id, so a caller cannot impersonate
        # another user to reach their orders. Falls back to the request body
        # only when no auth is configured (local/dev mode).
        effective_user_id = getattr(http_request.state, "user_id", None) or request.user_id
        msg = UserMessage(
            session_id=request.session_id,
            content=request.content,
            channel=request.channel,
            user_id=effective_user_id,
        )

        response: AgentMessage = await _orchestrator.handle_message(msg)
        adapter = _registry.get_adapter(request.channel)
        channel_msg = adapter.adapt_with_fallback(response)

        return ChatResponse(
            message_type=channel_msg.content_type,
            payload=channel_msg.payload,
            text_fallback=response.text_fallback,
            suggestions=response.suggestions,
            requires_confirmation=response.requires_confirmation,
        )

    # ------------------------------------------------------------------
    # SSE streaming chat
    # ------------------------------------------------------------------

    @app.post("/api/v1/chat/stream")
    async def chat_stream(
        http_request: Request,
        request: ChatRequest,
    ) -> StreamingResponse:
        # POST (not GET): the user message is sensitive (PII) and must travel in
        # the body, never in the URL query string where it would land in access
        # logs / proxies (audit MEDIUM). SSE clients use fetch()+ReadableStream.
        if _orchestrator is None:
            raise HTTPException(status_code=503, detail="Service not configured")
        session_id = request.session_id
        channel = request.channel

        # Session mode guard
        _s_mode = _session_modes.get(session_id)
        if _s_mode == SessionMode.HUMAN_MODE:
            raise HTTPException(
                status_code=423,
                detail="Session in human service mode",
            )
        if _context_manager is not None:
            ctx = _context_manager.get(session_id)
            if ctx is not None and ctx.mode == SessionMode.HUMAN_MODE:
                raise HTTPException(
                    status_code=423,
                    detail="Session in human service mode",
                )

        effective_user_id = getattr(http_request.state, "user_id", None) or request.user_id
        msg = UserMessage(
            session_id=session_id,
            content=request.content,
            channel=channel,
            user_id=effective_user_id,
        )
        streaming = StreamingOrchestrator(_orchestrator)
        sse_adapter = _registry.get_adapter(channel)

        async def event_generator() -> AsyncIterator[str]:
            async for event in streaming.handle_streaming(msg):
                if event.type == "done":
                    yield _build_done_event(event, sse_adapter).to_sse()
                else:
                    yield event.to_sse()

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
        )

    # ------------------------------------------------------------------
    # WebSocket chat (streaming)
    # ------------------------------------------------------------------

    @app.websocket("/ws/chat/{session_id}")
    async def websocket_chat(
        websocket: WebSocket,
        session_id: str,
        channel: str = Query("web"),
        token: str | None = Query(None),
        user_id: str | None = Query(None),
    ) -> None:
        await websocket.accept()
        _customer_sockets[session_id] = websocket
        ws_adapter = _registry.get_adapter(channel)

        # Bind identity from the server-verified JWT 'sub' (this entry bypasses
        # AuthMiddleware). When a secret IS configured, identity comes ONLY from
        # the verified token: an absent/invalid/expired token yields no identity
        # and the client-supplied ?user_id is NOT honoured (otherwise an attacker
        # could impersonate any user by presenting a bad token — the REST entry
        # already refuses this via AuthMiddleware's 401). The client ?user_id is
        # accepted as advisory ONLY when no secret is configured (local/dev),
        # matching the REST fail-open-when-auth-disabled posture.
        effective_user_id = (
            _resolve_ws_identity(token, jwt_secret) if jwt_secret else user_id
        )
        try:
            while True:
                data = await websocket.receive_text()

                # Handle client heartbeat — respond immediately and skip
                # normal processing so it is not treated as a chat message.
                try:
                    parsed = json.loads(data)
                    if isinstance(parsed, dict) and parsed.get("type") == "heartbeat":
                        await websocket.send_json({"type": "heartbeat"})
                        continue
                except (json.JSONDecodeError, ValueError):
                    pass  # not JSON — treat as plain text chat message

                if _orchestrator is None:
                    await websocket.send_json({"error": "Service not configured"})
                    continue

                # If session has active human transfer, forward to agent
                # Check context_manager first, then fall back to _session_modes
                _mode = None
                _agent_id = None
                if _context_manager is not None:
                    ctx = _context_manager.get(session_id)
                    if ctx is not None:
                        _mode = ctx.mode
                        _agent_id = ctx.human_agent_id
                if _mode is None:
                    _mode = _session_modes.get(session_id)

                if _mode == SessionMode.HUMAN_MODE:
                    agent_ws = _agent_sockets.get(_agent_id or "")
                    if agent_ws:
                        await agent_ws.send_text(json.dumps({
                            "type": "customer_message",
                            "data": {
                                "session_id": session_id,
                                "content": data,
                            },
                        }, ensure_ascii=False))
                    _append_session_message(
                        session_id, {"role": "user", "content": data}
                    )
                    continue

                if _mode == SessionMode.TRANSFER_PENDING:
                    _append_session_message(
                        session_id, {"role": "user", "content": data}
                    )
                    await websocket.send_text(json.dumps({
                        "type": "transfer_status",
                        "data": {"status": "waiting"},
                    }, ensure_ascii=False))
                    continue

                # Record user message
                _append_session_message(
                    session_id, {"role": "user", "content": data}
                )

                msg = UserMessage(
                    session_id=session_id,
                    content=data,
                    channel=channel,
                    user_id=effective_user_id,
                )
                streaming = StreamingOrchestrator(_orchestrator)
                async for event in streaming.handle_streaming(msg):
                    if event.type == "done":
                        await websocket.send_text(
                            _build_done_event(event, ws_adapter).to_json()
                        )
                        # Record assistant response
                        _append_session_message(session_id, {
                            "role": "assistant",
                            "content": event.data.get("text_fallback", ""),
                            "message_type": event.data.get("message_type"),
                            "payload": event.data.get("payload"),
                        })
                    else:
                        await websocket.send_text(event.to_json())
        except WebSocketDisconnect:
            _customer_sockets.pop(session_id, None)
            # Delayed cleanup: remove session messages after 300s so agent
            # dashboard can still fetch history after customer disconnects.
            _cleanup_task = asyncio.create_task(_delayed_session_cleanup(session_id))
            _background_tasks.add(_cleanup_task)
            _cleanup_task.add_done_callback(_background_tasks.discard)
            logger.info(
                "WebSocket disconnected",
                extra={"session_id": session_id},
            )

    # ------------------------------------------------------------------
    # Agent API
    # ------------------------------------------------------------------

    _handoff_queue = getattr(_orchestrator, "_handoff_queue", None) if _orchestrator else None
    _context_manager = getattr(_orchestrator, "_context_manager", None) if _orchestrator else None

    if _handoff_queue is not None:
        _agent_secret = os.environ.get("AGENT_SECRET", "") or None
        agent_router = create_agent_router(
            _handoff_queue,
            context_manager=_context_manager,
            session_messages=_session_messages,
            agent_secret=_agent_secret,
        )
        app.include_router(agent_router)

    # ------------------------------------------------------------------
    # Agent WebSocket
    # ------------------------------------------------------------------

    if _handoff_queue is not None:

        def _schedule_ws_send(websocket: WebSocket, payload: str) -> bool:
            """Schedule a fire-and-forget WS send on the running event loop.

            Returns ``True`` when the send was scheduled. The task is kept in
            ``_background_tasks`` so the loop holds a strong reference and the
            send cannot be garbage-collected mid-flight (per asyncio docs the
            loop only keeps a weak ref to bare tasks). ``get_running_loop`` is
            used deliberately over the deprecated ``get_event_loop`` so the
            send binds to the loop actually running this callback; if there is
            no running loop (a non-async caller) we log and report failure
            instead of raising. Send failures are logged, never swallowed
            silently, so a desynced dashboard leaves a trace.
            """
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                logger.warning("WS send skipped: no running event loop")
                return False
            task = loop.create_task(websocket.send_text(payload))
            _background_tasks.add(task)

            def _on_done(t: asyncio.Task[None]) -> None:
                _background_tasks.discard(t)
                exc = t.exception()
                if exc is not None:
                    logger.warning("WS send failed: %s", exc)

            task.add_done_callback(_on_done)
            return True

        def _notify_agents(event_type: str, data: dict[str, Any]) -> None:
            """Broadcast an event to all connected agent WebSockets."""
            msg = json.dumps({"type": event_type, "data": data}, ensure_ascii=False)
            dead: list[str] = []
            for aid, ws in _agent_sockets.items():
                if not _schedule_ws_send(ws, msg):
                    dead.append(aid)
            for aid in dead:
                _agent_sockets.pop(aid, None)

        def _on_enqueue_cb(request: TransferRequest, position: int) -> None:
            _notify_agents("new_request", {
                "request_id": request.request_id,
                "session_id": request.session_id,
                "reason": request.reason,
                "department": request.department,
                "position": position,
            })

        def _on_assign_cb(request: TransferRequest, agent: HumanAgent) -> None:
            # Update session context to HUMAN_MODE
            _session_modes[request.session_id] = SessionMode.HUMAN_MODE
            if _context_manager is not None:
                ctx = _context_manager.get(request.session_id)
                if ctx is not None:
                    ctx.mode = SessionMode.HUMAN_MODE
                    ctx.human_agent_id = agent.agent_id

            # Notify customer about agent assignment
            cust_ws = _customer_sockets.get(request.session_id)
            if cust_ws is not None:
                _schedule_ws_send(cust_ws, json.dumps({
                    "type": "transfer_status",
                    "data": {
                        "status": "connected",
                        "agent_name": agent.name,
                    },
                }, ensure_ascii=False))

            # Send the accumulated session history to the assigned agent
            # directly so they have context even if history fetch races
            agent_ws = _agent_sockets.get(agent.agent_id)
            if agent_ws is not None:
                history = _session_messages.get(request.session_id, [])
                _schedule_ws_send(agent_ws, json.dumps({
                    "type": "session_history",
                    "data": {
                        "session_id": request.session_id,
                        "messages": history,
                    },
                }, ensure_ascii=False))

            _notify_agents("request_assigned", {
                "session_id": request.session_id,
                "agent_id": agent.agent_id,
                "agent_name": agent.name,
            })

        def _on_complete_cb(transfer: TransferRequest) -> None:
            # Reset session context to AI_MODE
            _session_modes[transfer.session_id] = SessionMode.AI_MODE
            if _context_manager is not None:
                ctx = _context_manager.get(transfer.session_id)
                if ctx is not None:
                    ctx.mode = SessionMode.AI_MODE
                    ctx.human_agent_id = None

            # Notify customer that human service ended
            cust_ws = _customer_sockets.get(transfer.session_id)
            if cust_ws is not None:
                _schedule_ws_send(cust_ws, json.dumps({
                    "type": "transfer_ended",
                    "data": {"message": "人工服务已结束，已回到智能助手模式。"},
                }, ensure_ascii=False))

            _notify_agents("transfer_completed", {
                "session_id": transfer.session_id,
            })

        _handoff_queue._on_enqueue.append(_on_enqueue_cb)
        _handoff_queue._on_assign.append(_on_assign_cb)
        _handoff_queue._on_complete.append(_on_complete_cb)

    @app.websocket("/ws/agent/{agent_id}")
    async def agent_websocket(
        websocket: WebSocket,
        agent_id: str,
        name: str = Query(""),
        department: str = Query("general"),
    ) -> None:
        # Validate agent token when AGENT_TOKEN is configured
        if agent_token:
            ws_token = websocket.query_params.get("token", "")
            if not hmac.compare_digest(ws_token, agent_token):
                await websocket.close(code=4001, reason="Invalid agent token")
                return

        await websocket.accept()
        _agent_sockets[agent_id] = websocket

        # Auto-register agent if backend restarted and lost registration
        if _handoff_queue is not None and agent_id not in _handoff_queue._agents:
            from open_chat_shop.core.handoff import HumanAgent
            agent = HumanAgent(
                agent_id=agent_id,
                name=name or f"坐席{agent_id[-4:]}",
                department=department,
            )
            _handoff_queue.register_agent(agent)
            logger.info("Auto-registered agent %s on WS connect", agent_id)

        # Send current queue state on connect
        if _handoff_queue is not None:
            queue_items = []
            for i, req in enumerate(_handoff_queue._queue):
                queue_items.append({
                    "request_id": req.request_id,
                    "session_id": req.session_id,
                    "reason": req.reason,
                    "position": i + 1,
                })
            await websocket.send_text(json.dumps({
                "type": "queue_state",
                "data": {"queue": queue_items},
            }, ensure_ascii=False))

        try:
            while True:
                data = await websocket.receive_text()
                msg = json.loads(data)
                msg_type = msg.get("type", "")
                msg_data = msg.get("data", {})

                if msg_type == "agent_message":
                    session_id = msg_data.get("session_id", "")
                    content = msg_data.get("content", "")

                    # Forward directly to customer WebSocket
                    cust_ws = _customer_sockets.get(session_id)
                    if cust_ws:
                        await cust_ws.send_text(json.dumps({
                            "type": "agent_message",
                            "data": {
                                "content": content,
                                "agent_name": msg_data.get("agent_name", "客服"),
                            },
                        }, ensure_ascii=False))

                    # Confirm to agent
                    await websocket.send_text(json.dumps({
                        "type": "message_sent",
                        "data": {
                            "session_id": session_id,
                            "content": content,
                        },
                    }, ensure_ascii=False))

                elif msg_type == "heartbeat":
                    await websocket.send_text(json.dumps({"type": "heartbeat"}))

        except WebSocketDisconnect:
            _agent_sockets.pop(agent_id, None)
            logger.info("Agent WebSocket disconnected", extra={"agent_id": agent_id})
        except Exception:
            _agent_sockets.pop(agent_id, None)

    # ------------------------------------------------------------------
    # WeChat webhook
    # ------------------------------------------------------------------

    if _orchestrator is not None:
        setup_wechat_routes(app, _orchestrator)

    # ------------------------------------------------------------------
    # Prometheus metrics endpoint
    # ------------------------------------------------------------------

    try:
        from open_chat_shop.observability.metrics import metrics_app as _metrics_app

        if _metrics_app is not None:
            app.mount("/metrics", cast(ASGIApp, _metrics_app))
    except Exception:
        logger.debug("Prometheus metrics endpoint not mounted")

    return app


# Default app for development / uvicorn
app = create_app()
