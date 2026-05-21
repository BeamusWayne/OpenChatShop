"""Agent-facing REST API endpoints for the human agent dashboard."""
from __future__ import annotations

import uuid
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from open_chat_shop.core.handoff import AgentStatus, HandoffQueue, HumanAgent
from open_chat_shop.core.types import AgentMessage, SessionMode


# ---- Request / Response models ----

class RegisterRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    department: str = Field("general", max_length=50)
    secret: Optional[str] = Field(None, max_length=128)


class RegisterResponse(BaseModel):
    agent_id: str
    name: str
    department: str


class StatusRequest(BaseModel):
    status: str


class QueueItemResponse(BaseModel):
    request_id: str
    session_id: str
    reason: str
    department: str
    queued_at: str
    priority: int
    position: int


class ActiveSessionResponse(BaseModel):
    session_id: str
    request_id: str
    reason: str
    assigned_at: str | None


class AgentInfoResponse(BaseModel):
    agent_id: str
    name: str
    department: str
    status: str
    active_session_count: int


def create_agent_router(
    handoff_queue: HandoffQueue,
    context_manager: Any = None,
    session_messages: dict[str, list[dict]] | None = None,
    agent_secret: str | None = None,
) -> APIRouter:
    """Build and return a FastAPI router with agent endpoints.

    *agent_secret* is an optional shared secret.  When set, the register
    endpoint requires ``secret`` in the request body and the status-update
    endpoint requires the ``X-Agent-Secret`` header.  When not set, both
    endpoints are open (backward compatible).
    """
    router = APIRouter(prefix="/api/v1/agent", tags=["agent"])

    @router.post("/register", response_model=RegisterResponse)
    async def register(body: RegisterRequest) -> RegisterResponse:
        if agent_secret is not None:
            if body.secret != agent_secret:
                raise HTTPException(
                    status_code=401,
                    detail="Invalid agent secret",
                )
        agent_id = f"agent-{uuid.uuid4().hex[:8]}"
        agent = HumanAgent(
            agent_id=agent_id,
            name=body.name,
            department=body.department,
        )
        handoff_queue.register_agent(agent)
        return RegisterResponse(
            agent_id=agent_id,
            name=body.name,
            department=body.department,
        )

    @router.get("/agents", response_model=list[AgentInfoResponse])
    async def list_agents() -> list[AgentInfoResponse]:
        return [
            AgentInfoResponse(
                agent_id=a.agent_id,
                name=a.name,
                department=a.department,
                status=a.status.value,
                active_session_count=len(a.active_sessions),
            )
            for a in handoff_queue.get_online_agents()
        ]

    @router.put("/{agent_id}/status")
    async def update_status(
        agent_id: str,
        body: StatusRequest,
        x_agent_secret: str | None = Header(default=None),
    ) -> dict[str, str]:
        if agent_secret is not None:
            if x_agent_secret != agent_secret:
                raise HTTPException(
                    status_code=401,
                    detail="Invalid agent secret",
                )
        agent = handoff_queue._agents.get(agent_id)
        if agent is None:
            raise HTTPException(status_code=404, detail="Agent not found")
        try:
            agent.status = AgentStatus(body.status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {body.status}")
        return {"status": "ok"}

    @router.get("/queue", response_model=list[QueueItemResponse])
    async def get_queue() -> list[QueueItemResponse]:
        items = []
        for i, r in enumerate(handoff_queue._queue):
            items.append(QueueItemResponse(
                request_id=r.request_id,
                session_id=r.session_id,
                reason=r.reason,
                department=r.department,
                queued_at=r.queued_at.isoformat(),
                priority=r.priority,
                position=i + 1,
            ))
        return items

    @router.get("/active", response_model=list[ActiveSessionResponse])
    async def get_active() -> list[ActiveSessionResponse]:
        return [
            ActiveSessionResponse(
                session_id=sid,
                request_id=r.request_id,
                reason=r.reason,
                assigned_at=r.assigned_at.isoformat() if r.assigned_at else None,
            )
            for sid, r in handoff_queue._active_transfers.items()
        ]

    @router.get("/history/{session_id}")
    async def get_history(session_id: str) -> dict[str, Any]:
        if session_messages is None:
            return {"messages": []}
        return {"messages": session_messages.get(session_id, [])}

    @router.post("/accept/{session_id}")
    async def accept_session(session_id: str) -> dict[str, Any]:
        # Check if already assigned (idempotent for auto-assigned sessions)
        existing = handoff_queue.get_active_transfer(session_id)
        if existing is not None and existing.assigned_agent_id:
            agent = handoff_queue._agents.get(existing.assigned_agent_id)
            return {
                "status": "already_assigned",
                "session_id": session_id,
                "agent_id": existing.assigned_agent_id,
                "agent_name": agent.name if agent else "客服",
                "context": {
                    "messages": session_messages.get(session_id, []) if session_messages else [],
                    "transfer_reason": existing.reason,
                },
            }

        request = None
        for r in handoff_queue._queue:
            if r.session_id == session_id:
                request = r
                break
        if request is None:
            raise HTTPException(status_code=404, detail="Session not in queue")

        agent = handoff_queue.assign(request)
        if agent is None:
            raise HTTPException(status_code=409, detail="No available agents")

        # Set session context to HUMAN_MODE
        if context_manager is not None:
            ctx = await context_manager.load(session_id)
            ctx.mode = SessionMode.HUMAN_MODE
            ctx.human_agent_id = agent.agent_id
            await context_manager.save(ctx, AgentMessage(message_type="text", payload={}, text_fallback=""))

        # Build context payload for the agent
        context_data: dict[str, Any] = {}
        if session_messages is not None:
            context_data["messages"] = session_messages.get(session_id, [])
        if context_manager is not None:
            ctx = await context_manager.load(session_id)
            context_data["intents"] = list({
                m.get("intent", "") for m in session_messages.get(session_id, [])
                if m.get("intent")
            })
            context_data["duration_with_ai"] = int(
                (ctx.last_active_at - ctx.created_at).total_seconds()
            ) if ctx.created_at else 0
        context_data["transfer_reason"] = request.reason

        return {
            "status": "assigned",
            "session_id": session_id,
            "agent_id": agent.agent_id,
            "agent_name": agent.name,
            "context": context_data,
        }

    @router.post("/complete/{session_id}")
    async def complete_session(session_id: str) -> dict[str, str]:
        if session_id not in handoff_queue._active_transfers:
            raise HTTPException(status_code=404, detail="No active transfer for session")
        handoff_queue.complete_transfer(session_id)
        # Context reset happens via _on_complete_cb in app.py
        return {"status": "completed"}

    return router
