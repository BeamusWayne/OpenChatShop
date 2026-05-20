"""Agent-facing REST API endpoints for the human agent dashboard."""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from open_chat_shop.core.handoff import AgentStatus, HandoffQueue, HumanAgent


# ---- Request / Response models ----

class RegisterRequest(BaseModel):
    name: str
    department: str = "general"


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


def create_agent_router(handoff_queue: HandoffQueue) -> APIRouter:
    """Build and return a FastAPI router with agent endpoints."""
    router = APIRouter(prefix="/api/v1/agent", tags=["agent"])

    @router.post("/register", response_model=RegisterResponse)
    async def register(body: RegisterRequest) -> RegisterResponse:
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
    async def update_status(agent_id: str, body: StatusRequest) -> dict[str, str]:
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

    @router.post("/accept/{session_id}")
    async def accept_session(session_id: str) -> dict[str, Any]:
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

        return {
            "status": "assigned",
            "session_id": session_id,
            "agent_id": agent.agent_id,
            "agent_name": agent.name,
        }

    @router.post("/complete/{session_id}")
    async def complete_session(session_id: str) -> dict[str, str]:
        if session_id not in handoff_queue._active_transfers:
            raise HTTPException(status_code=404, detail="No active transfer for session")
        handoff_queue.complete_transfer(session_id)
        return {"status": "completed"}

    return router
