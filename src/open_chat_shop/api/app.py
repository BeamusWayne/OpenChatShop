"""FastAPI application — REST + WebSocket endpoints."""
from __future__ import annotations

import importlib.metadata
import logging
import os
from typing import Any, Callable, Optional

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
import asyncio
import json
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware as _BaseMiddleware

from open_chat_shop.api.auth import AuthMiddleware
from open_chat_shop.core.types import AgentMessage, UserMessage, SessionMode
from open_chat_shop.core.orchestrator import DialogueOrchestrator
from open_chat_shop.channel.registry import default_registry
from open_chat_shop.api.streaming import StreamEvent, StreamingOrchestrator
from open_chat_shop.api.wechat import setup_wechat_routes
from open_chat_shop.api.agent import create_agent_router

logger = logging.getLogger(__name__)

try:
    _VERSION = importlib.metadata.version("open-chat-shop")
except importlib.metadata.PackageNotFoundError:
    _VERSION = "0.1.0"


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    session_id: str
    content: str
    channel: str = "web"
    user_id: Optional[str] = None


class ChatResponse(BaseModel):
    message_type: str
    payload: dict
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
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'"
        )
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
    lifespan: Callable | None = None,
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
    _session_messages: dict[str, list[dict]] = {}

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
    async def chat(request: ChatRequest) -> ChatResponse:
        if _orchestrator is None:
            raise HTTPException(status_code=503, detail="Service not configured")

        # Session mode guard: reject when in human service mode
        if _context_manager is not None:
            ctx = _context_manager.get(request.session_id)
            if ctx is not None and ctx.mode == SessionMode.HUMAN_MODE:
                raise HTTPException(
                    status_code=423,
                    detail="Session in human service mode",
                )

        msg = UserMessage(
            session_id=request.session_id,
            content=request.content,
            channel=request.channel,
            user_id=request.user_id,
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

    @app.get("/api/v1/chat/stream")
    async def chat_stream(
        session_id: str = Query(...),
        content: str = Query(...),
        channel: str = Query("web"),
        user_id: Optional[str] = Query(None),
    ) -> StreamingResponse:
        if _orchestrator is None:
            raise HTTPException(status_code=503, detail="Service not configured")

        # Session mode guard
        if _context_manager is not None:
            ctx = _context_manager.get(session_id)
            if ctx is not None and ctx.mode == SessionMode.HUMAN_MODE:
                raise HTTPException(
                    status_code=423,
                    detail="Session in human service mode",
                )

        msg = UserMessage(
            session_id=session_id,
            content=content,
            channel=channel,
            user_id=user_id,
        )
        streaming = StreamingOrchestrator(_orchestrator)
        sse_adapter = _registry.get_adapter(channel)

        async def event_generator():
            async for event in streaming.handle_streaming(msg):
                if event.type == "done":
                    # Reconstruct AgentMessage from done event data and adapt
                    agent_msg = AgentMessage(
                        message_type=event.data.get("message_type", "text"),
                        payload=event.data.get("payload", {}),
                        text_fallback=event.data.get("payload", {}).get(
                            "content", ""
                        ),
                    )
                    channel_msg = sse_adapter.adapt_with_fallback(agent_msg)
                    yield StreamEvent(
                        type="done",
                        data={
                            "message_type": channel_msg.content_type,
                            "payload": channel_msg.payload,
                            "suggestions": event.data.get("suggestions", []),
                            "requires_confirmation": event.data.get(
                                "requires_confirmation", False
                            ),
                        },
                    ).to_sse()
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
    ) -> None:
        await websocket.accept()
        _customer_sockets[session_id] = websocket
        ws_adapter = _registry.get_adapter(channel)
        try:
            while True:
                data = await websocket.receive_text()
                if _orchestrator is None:
                    await websocket.send_json({"error": "Service not configured"})
                    continue

                # If session has active human transfer, forward to agent
                if _context_manager is not None:
                    ctx = _context_manager.get(session_id)
                    logger.info(
                        "WS mode check: session=%s ctx=%s mode=%s",
                        session_id, ctx is not None,
                        ctx.mode if ctx else "N/A",
                    )
                    if ctx is not None and ctx.mode == SessionMode.HUMAN_MODE:
                        agent_ws = _agent_sockets.get(ctx.human_agent_id or "")
                        logger.info(
                            "HUMAN_MODE forward: agent_id=%s ws_found=%s",
                            ctx.human_agent_id, agent_ws is not None,
                        )
                        if agent_ws:
                            await agent_ws.send_text(json.dumps({
                                "type": "customer_message",
                                "data": {
                                    "session_id": session_id,
                                    "content": data,
                                },
                            }, ensure_ascii=False))
                        _session_messages.setdefault(session_id, []).append({
                            "role": "user",
                            "content": data,
                        })
                        continue

                    if ctx is not None and ctx.mode == SessionMode.TRANSFER_PENDING:
                        _session_messages.setdefault(session_id, []).append({
                            "role": "user",
                            "content": data,
                        })
                        await websocket.send_text(json.dumps({
                            "type": "transfer_status",
                            "data": {"status": "waiting"},
                        }, ensure_ascii=False))
                        continue

                # Record user message
                _session_messages.setdefault(session_id, []).append({
                    "role": "user",
                    "content": data,
                })

                msg = UserMessage(
                    session_id=session_id,
                    content=data,
                    channel=channel,
                )
                streaming = StreamingOrchestrator(_orchestrator)
                async for event in streaming.handle_streaming(msg):
                    if event.type == "done":
                        agent_msg = AgentMessage(
                            message_type=event.data.get("message_type", "text"),
                            payload=event.data.get("payload", {}),
                            text_fallback=event.data.get("payload", {}).get(
                                "content", ""
                            ),
                        )
                        channel_msg = ws_adapter.adapt_with_fallback(agent_msg)
                        await websocket.send_text(
                            StreamEvent(
                                type="done",
                                data={
                                    "message_type": channel_msg.content_type,
                                    "payload": channel_msg.payload,
                                    "suggestions": event.data.get("suggestions", []),
                                    "requires_confirmation": event.data.get(
                                        "requires_confirmation", False
                                    ),
                                },
                            ).to_json()
                        )
                        # Record assistant response
                        _session_messages[session_id].append({
                            "role": "assistant",
                            "content": event.data.get("payload", {}).get("content", ""),
                            "message_type": event.data.get("message_type"),
                            "payload": event.data.get("payload"),
                        })
                    else:
                        await websocket.send_text(event.to_json())
        except WebSocketDisconnect:
            _customer_sockets.pop(session_id, None)
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
        agent_router = create_agent_router(
            _handoff_queue,
            context_manager=_context_manager,
            session_messages=_session_messages,
        )
        app.include_router(agent_router)

    # ------------------------------------------------------------------
    # Agent WebSocket
    # ------------------------------------------------------------------

    if _handoff_queue is not None:

        def _notify_agents(event_type: str, data: dict) -> None:
            """Broadcast an event to all connected agent WebSockets."""
            msg = json.dumps({"type": event_type, "data": data}, ensure_ascii=False)
            dead = []
            for aid, ws in _agent_sockets.items():
                try:
                    import asyncio as _aio
                    _aio.get_event_loop().create_task(ws.send_text(msg))
                except Exception:
                    dead.append(aid)
            for aid in dead:
                _agent_sockets.pop(aid, None)

        def _on_enqueue_cb(request, position: int) -> None:
            _notify_agents("new_request", {
                "request_id": request.request_id,
                "session_id": request.session_id,
                "reason": request.reason,
                "department": request.department,
                "position": position,
            })

        def _on_assign_cb(request, agent) -> None:
            # Update session context to HUMAN_MODE
            if _context_manager is not None:
                ctx = _context_manager.get(request.session_id)
                logger.info(
                    "on_assign: session=%s ctx_found=%s",
                    request.session_id, ctx is not None,
                )
                if ctx is not None:
                    ctx.mode = SessionMode.HUMAN_MODE
                    ctx.human_agent_id = agent.agent_id

            # Notify customer about agent assignment
            cust_ws = _customer_sockets.get(request.session_id)
            logger.info(
                "on_assign notify customer: session=%s cust_ws=%s",
                request.session_id, cust_ws is not None,
            )
            if cust_ws is not None:
                try:
                    import asyncio as _aio
                    _aio.get_event_loop().create_task(cust_ws.send_text(json.dumps({
                        "type": "transfer_status",
                        "data": {
                            "status": "connected",
                            "agent_name": agent.name,
                        },
                    }, ensure_ascii=False)))
                except Exception:
                    pass

            _notify_agents("request_assigned", {
                "session_id": request.session_id,
                "agent_id": agent.agent_id,
                "agent_name": agent.name,
            })

        def _on_complete_cb(transfer) -> None:
            # Reset session context to AI_MODE
            if _context_manager is not None:
                ctx = _context_manager.get(transfer.session_id)
                if ctx is not None:
                    ctx.mode = SessionMode.AI_MODE
                    ctx.human_agent_id = None

            # Notify customer that human service ended
            cust_ws = _customer_sockets.get(transfer.session_id)
            if cust_ws is not None:
                try:
                    import asyncio as _aio
                    _aio.get_event_loop().create_task(cust_ws.send_text(json.dumps({
                        "type": "transfer_ended",
                        "data": {"message": "人工服务已结束，已回到智能助手模式。"},
                    }, ensure_ascii=False)))
                except Exception:
                    pass

            _notify_agents("transfer_completed", {
                "session_id": transfer.session_id,
            })

        _handoff_queue._on_enqueue.append(_on_enqueue_cb)
        _handoff_queue._on_assign.append(_on_assign_cb)
        _handoff_queue._on_complete.append(_on_complete_cb)

    @app.websocket("/ws/agent/{agent_id}")
    async def agent_websocket(websocket: WebSocket, agent_id: str) -> None:
        await websocket.accept()
        _agent_sockets[agent_id] = websocket

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
            app.mount("/metrics", _metrics_app)
    except Exception:
        logger.debug("Prometheus metrics endpoint not mounted")

    return app


# Default app for development / uvicorn
app = create_app()
