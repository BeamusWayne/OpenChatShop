"""FastAPI application — REST + WebSocket endpoints."""
from __future__ import annotations

import logging
from typing import Optional

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from open_chat_shop.core.types import AgentMessage, UserMessage
from open_chat_shop.core.orchestrator import DialogueOrchestrator
from open_chat_shop.channel.web import WebAdapter
from open_chat_shop.api.streaming import StreamEvent, StreamingOrchestrator

logger = logging.getLogger(__name__)


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
        version="0.1.0",
        description="E-commerce intelligent dialogue system",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    web_adapter = WebAdapter()
    _orchestrator = orchestrator

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(status="ok", version="0.1.0")

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
        channel_msg = web_adapter.adapt_with_fallback(response)

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

        async def event_generator():
            async for event in streaming.handle_streaming(msg):
                yield event.to_sse()

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
        )

    # ------------------------------------------------------------------
    # WebSocket chat (streaming)
    # ------------------------------------------------------------------

    @app.websocket("/ws/chat/{session_id}")
    async def websocket_chat(websocket: WebSocket, session_id: str) -> None:
        await websocket.accept()
        try:
            while True:
                data = await websocket.receive_text()
                if _orchestrator is None:
                    await websocket.send_json({"error": "Service not configured"})
                    continue

                msg = UserMessage(
                    session_id=session_id,
                    content=data,
                    channel="web",
                )
                streaming = StreamingOrchestrator(_orchestrator)
                async for event in streaming.handle_streaming(msg):
                    await websocket.send_text(event.to_json())
        except WebSocketDisconnect:
            logger.info(
                "WebSocket disconnected",
                extra={"session_id": session_id},
            )

    # Mount static files for the chat widget UI
    static_dir = Path(__file__).resolve().parent.parent.parent.parent / "static"
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app


# Default app for development / uvicorn
app = create_app()
