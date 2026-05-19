"""FastAPI application — REST + WebSocket endpoints."""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from commerce_agent.core.types import AgentMessage, UserMessage
from commerce_agent.core.orchestrator import DialogueOrchestrator
from commerce_agent.channel.web import WebAdapter

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
        title="CommerceAgent API",
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
    # WebSocket chat
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
                response: AgentMessage = await _orchestrator.handle_message(msg)
                channel_msg = web_adapter.adapt_with_fallback(response)
                await websocket.send_json(channel_msg.payload)
        except WebSocketDisconnect:
            logger.info(
                "WebSocket disconnected",
                extra={"session_id": session_id},
            )

    return app


# Default app for development / uvicorn
app = create_app()
