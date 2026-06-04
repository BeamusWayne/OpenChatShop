"""Human handoff queue management.

Manages agent (human customer service representative) registration,
session assignment, queue tracking, and timeout escalation.
"""
from __future__ import annotations

import contextlib
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    """Return the current time as a tz-aware UTC datetime.

    Centralised so every timestamp in this module is offset-aware and
    comparisons (e.g. in :meth:`HandoffQueue.check_timeouts`) never mix
    naive and aware datetimes.
    """
    return datetime.now(UTC)


class AgentStatus(StrEnum):
    OFFLINE = "offline"
    ONLINE = "online"
    BUSY = "busy"


class TransferStatus(StrEnum):
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
    # tz-aware (UTC) so it can be compared against datetime.now(UTC) in
    # check_timeouts without raising "can't subtract offset-naive and
    # offset-aware datetimes".
    queued_at: datetime = field(default_factory=_utcnow)
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
        # Optional callbacks for real-time notifications
        self._on_enqueue: list[Any] = []   # Called with (TransferRequest, position)
        self._on_assign: list[Any] = []    # Called with (TransferRequest, HumanAgent)
        self._on_complete: list[Any] = []  # Called with (TransferRequest)

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
        position = self._queue.index(request) + 1
        for cb in self._on_enqueue:
            with contextlib.suppress(Exception):
                cb(request, position)
        return position

    def assign(self, request: TransferRequest) -> HumanAgent | None:
        """Try to assign a request to an available agent.

        Uses least-load strategy: picks the agent with the fewest
        active sessions. Falls back to any department if no exact match.
        """
        available = [
            a for a in self.get_online_agents(request.department)
            if len(a.active_sessions) < a.max_concurrent
        ]
        if not available:
            # Fall back to any online agent regardless of department
            available = [
                a for a in self.get_online_agents()
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
        request.assigned_at = _utcnow()

        self._active_transfers[request.session_id] = request
        # Remove from queue if present
        self._queue = [r for r in self._queue if r.request_id != request.request_id]

        logger.info(
            "Assigned session %s to agent %s",
            request.session_id, agent.name,
        )
        for cb in self._on_assign:
            with contextlib.suppress(Exception):
                cb(request, agent)
        return agent

    def complete_transfer(self, session_id: str) -> None:
        """Mark a transfer as completed, freeing the agent."""
        transfer = self._active_transfers.pop(session_id, None)
        if transfer is None:
            return

        transfer.status = TransferStatus.COMPLETED
        transfer.completed_at = _utcnow()

        agent = self._agents.get(transfer.assigned_agent_id or "")
        if agent:
            agent.active_sessions = [
                s for s in agent.active_sessions if s != session_id
            ]
            agent.status = AgentStatus.ONLINE

        for cb in self._on_complete:
            with contextlib.suppress(Exception):
                cb(transfer)

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
        now = _utcnow()
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

    def try_auto_assign(self) -> TransferRequest | None:
        """Try to assign the highest-priority queued request to an agent.

        Returns the assigned request, or None if no assignment was possible.
        """
        if not self._queue:
            return None
        # Pick highest-priority request
        request = self._queue[0]
        agent = self.assign(request)
        if agent is None:
            return None
        return request

    def get_active_transfer(self, session_id: str) -> TransferRequest | None:
        """Get the active transfer for a session, if any."""
        return self._active_transfers.get(session_id)

    def get_queued_request(self, session_id: str) -> TransferRequest | None:
        """Get a queued request by session_id, if any."""
        for req in self._queue:
            if req.session_id == session_id:
                return req
        return None
