"""FastAPI application — REST + WebSocket endpoints."""
from __future__ import annotations

import importlib.metadata
import logging
import os
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
import asyncio
import json
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from open_chat_shop.api.auth import AuthMiddleware
from open_chat_shop.core.types import AgentMessage, UserMessage
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


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------


def create_app(orchestrator: DialogueOrchestrator | None = None) -> FastAPI:
    """Build and return a configured FastAPI application.

    *orchestrator* may be ``None`` — in that case chat endpoints return 503,
    but /health still works.
    """
    app = FastAPI(
        title="OpenChatShop API",
        version=_VERSION,
        description="E-commerce intelligent dialogue system",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

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

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(status="ok", version=_VERSION)

    # ------------------------------------------------------------------
    # REST chat
    # ------------------------------------------------------------------

    @app.post("/api/v1/chat", response_model=ChatResponse)
    async def chat(request: ChatRequest) -> ChatResponse:
        if _orchestrator is None:
            raise HTTPException(status_code=503, detail="Service not configured")

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
        ws_adapter = _registry.get_adapter(channel)
        try:
            while True:
                data = await websocket.receive_text()
                if _orchestrator is None:
                    await websocket.send_json({"error": "Service not configured"})
                    continue

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
                    else:
                        await websocket.send_text(event.to_json())
        except WebSocketDisconnect:
            logger.info(
                "WebSocket disconnected",
                extra={"session_id": session_id},
            )

    # ------------------------------------------------------------------
    # Agent API
    # ------------------------------------------------------------------

    _handoff_queue = getattr(_orchestrator, "_handoff_queue", None) if _orchestrator else None

    if _handoff_queue is not None:
        agent_router = create_agent_router(_handoff_queue)
        app.include_router(agent_router)

    # ------------------------------------------------------------------
    # Agent WebSocket
    # ------------------------------------------------------------------

    # Track connected agent WebSockets: agent_id -> WebSocket
    _agent_sockets: dict[str, WebSocket] = {}

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
            _notify_agents("request_assigned", {
                "session_id": request.session_id,
                "agent_id": agent.agent_id,
                "agent_name": agent.name,
            })

        def _on_complete_cb(transfer) -> None:
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

                if msg_type == "agent_message" and _orchestrator is not None:
                    # Agent sends a message to a customer session
                    session_id = msg_data.get("session_id", "")
                    content = msg_data.get("content", "")

                    # Find customer WebSocket for this session
                    # For now, use the orchestrator to process the message
                    # as if it came from the agent
                    cust_msg = UserMessage(
                        session_id=session_id,
                        content=f"[人工客服] {content}",
                        channel="web",
                    )
                    response = await _orchestrator.handle_message(cust_msg)
                    # The response goes through the normal customer WS flow
                    # We'll send it back to the agent for confirmation
                    await websocket.send_text(json.dumps({
                        "type": "message_sent",
                        "data": {
                            "session_id": session_id,
                            "content": content,
                            "response": response.text_fallback,
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

    return app


# Default app for development / uvicorn
app = create_app()
