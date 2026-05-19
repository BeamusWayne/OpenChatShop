"""Human handoff queue management.

Manages agent (human customer service representative) registration,
session assignment, queue tracking, and timeout escalation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
import asyncio

import logging

logger = logging.getLogger(__name__)


class AgentStatus(str, Enum):
    OFFLINE = "offline"
    ONLINE = "online"
    BUSY = "busy"


class TransferStatus(str, Enum):
    QUEUED = "queued"
    ASSIGNED = "assigned"
    ACTIVE = "active"
    COMPLETED = "completed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass
class HumanAgent:
    """A human customer service agent."""
    agent_id: str
    name: str
    department: str = "general"
    status: AgentStatus = AgentStatus.OFFLINE
    max_concurrent: int = 3
    active_sessions: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)


@dataclass
class TransferRequest:
    """A request to transfer a session to a human agent."""
    request_id: str
    session_id: str
    user_id: str | None
    reason: str
    department: str = "general"
    status: TransferStatus = TransferStatus.QUEUED
    assigned_agent_id: str | None = None
    queued_at: datetime = field(default_factory=datetime.utcnow)
    assigned_at: datetime | None = None
    completed_at: datetime | None = None
    priority: int = 0  # Higher = more urgent


class HandoffQueue:
    """Manage human agent queue and session transfers.

    Supports:
    - Agent registration/deregistration
    - Round-robin and least-load assignment
    - Queue position tracking
    - Timeout escalation
    """

    def __init__(self, timeout_seconds: int = 300) -> None:
        self._agents: dict[str, HumanAgent] = {}
        self._queue: list[TransferRequest] = []
        self._active_transfers: dict[str, TransferRequest] = {}
        self._timeout_seconds = timeout_seconds

    def register_agent(self, agent: HumanAgent) -> None:
        """Register a human agent."""
        agent.status = AgentStatus.ONLINE
        self._agents[agent.agent_id] = agent
        logger.info("Agent registered: %s (%s)", agent.name, agent.department)

    def deregister_agent(self, agent_id: str) -> None:
        """Deregister a human agent."""
        agent = self._agents.pop(agent_id, None)
        if agent:
            logger.info("Agent deregistered: %s", agent.name)

    def get_online_agents(self, department: str | None = None) -> list[HumanAgent]:
        """Get all online agents, optionally filtered by department."""
        agents = [
            a for a in self._agents.values()
            if a.status in (AgentStatus.ONLINE, AgentStatus.BUSY)
        ]
        if department:
            agents = [a for a in agents if a.department == department]
        return agents

    def enqueue(self, request: TransferRequest) -> int:
        """Add a transfer request to the queue. Returns queue position."""
        self._queue.append(request)
        self._queue.sort(key=lambda r: r.priority, reverse=True)
        return self._queue.index(request) + 1

    def assign(self, request: TransferRequest) -> HumanAgent | None:
        """Try to assign a request to an available agent.

        Uses least-load strategy: picks the agent with the fewest
        active sessions.
        """
        available = [
            a for a in self.get_online_agents(request.department)
            if len(a.active_sessions) < a.max_concurrent
        ]
        if not available:
            return None

        # Least-load assignment
        available.sort(key=lambda a: len(a.active_sessions))
        agent = available[0]

        # Update state
        agent.active_sessions.append(request.session_id)
        if len(agent.active_sessions) >= agent.max_concurrent:
            agent.status = AgentStatus.BUSY

        request.status = TransferStatus.ASSIGNED
        request.assigned_agent_id = agent.agent_id
        request.assigned_at = datetime.utcnow()

        self._active_transfers[request.session_id] = request
        # Remove from queue if present
        self._queue = [r for r in self._queue if r.request_id != request.request_id]

        logger.info(
            "Assigned session %s to agent %s",
            request.session_id, agent.name,
        )
        return agent

    def complete_transfer(self, session_id: str) -> None:
        """Mark a transfer as completed, freeing the agent."""
        transfer = self._active_transfers.pop(session_id, None)
        if transfer is None:
            return

        transfer.status = TransferStatus.COMPLETED
        transfer.completed_at = datetime.utcnow()

        agent = self._agents.get(transfer.assigned_agent_id or "")
        if agent:
            agent.active_sessions = [
                s for s in agent.active_sessions if s != session_id
            ]
            agent.status = AgentStatus.ONLINE

    def get_queue_position(self, session_id: str) -> int | None:
        """Get the queue position for a session. None if not queued."""
        for i, req in enumerate(self._queue):
            if req.session_id == session_id:
                return i + 1
        return None

    def get_queue_length(self) -> int:
        """Get the total number of queued requests."""
        return len(self._queue)

    def get_estimated_wait(self, session_id: str) -> int:
        """Estimate wait time in seconds for a queued session."""
        position = self.get_queue_position(session_id)
        if position is None:
            return 0
        available_agents = len(self.get_online_agents())
        if available_agents == 0:
            return self._timeout_seconds
        avg_handle_time = 120  # seconds estimate
        return (position // available_agents) * avg_handle_time

    def check_timeouts(self) -> list[TransferRequest]:
        """Check for timed-out queued requests. Returns timed-out list."""
        now = datetime.utcnow()
        timed_out = []
        remaining = []
        for req in self._queue:
            elapsed = (now - req.queued_at).total_seconds()
            if elapsed >= self._timeout_seconds:
                req.status = TransferStatus.TIMEOUT
                timed_out.append(req)
            else:
                remaining.append(req)
        self._queue = remaining
        return timed_out

    def cancel(self, session_id: str) -> bool:
        """Cancel a queued transfer. Returns True if found and cancelled."""
        for i, req in enumerate(self._queue):
            if req.session_id == session_id:
                req.status = TransferStatus.CANCELLED
                self._queue.pop(i)
                return True
        return False
