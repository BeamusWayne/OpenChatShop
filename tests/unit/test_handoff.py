"""Tests for human handoff queue management."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from open_chat_shop.core.handoff import (
    AgentStatus,
    HandoffQueue,
    HumanAgent,
    TransferRequest,
    TransferStatus,
)


def _make_agent(agent_id: str = "a1", department: str = "general") -> HumanAgent:
    return HumanAgent(agent_id=agent_id, name=f"Agent {agent_id}", department=department)


def _make_request(session_id: str = "s1", department: str = "general",
                   priority: int = 0) -> TransferRequest:
    return TransferRequest(
        request_id=f"req-{session_id}",
        session_id=session_id,
        user_id="u1",
        reason="user request",
        department=department,
        priority=priority,
    )


class TestAgentManagement:
    @pytest.mark.unit
    def test_register_agent(self):
        queue = HandoffQueue()
        agent = _make_agent()
        queue.register_agent(agent)
        agents = queue.get_online_agents()
        assert len(agents) == 1
        assert agents[0].agent_id == "a1"

    @pytest.mark.unit
    def test_deregister_agent(self):
        queue = HandoffQueue()
        queue.register_agent(_make_agent())
        queue.deregister_agent("a1")
        assert queue.get_online_agents() == []

    @pytest.mark.unit
    def test_filter_by_department(self):
        queue = HandoffQueue()
        queue.register_agent(_make_agent("a1", "sales"))
        queue.register_agent(_make_agent("a2", "support"))
        assert len(queue.get_online_agents("sales")) == 1
        assert len(queue.get_online_agents("support")) == 1

    @pytest.mark.unit
    def test_agent_online_after_register(self):
        queue = HandoffQueue()
        agent = _make_agent()
        assert agent.status == AgentStatus.OFFLINE
        queue.register_agent(agent)
        assert agent.status == AgentStatus.ONLINE


class TestTransferQueue:
    @pytest.mark.unit
    def test_enqueue_returns_position(self):
        queue = HandoffQueue()
        pos = queue.enqueue(_make_request("s1"))
        assert pos == 1
        pos2 = queue.enqueue(_make_request("s2"))
        assert pos2 == 2

    @pytest.mark.unit
    def test_assign_to_available_agent(self):
        queue = HandoffQueue()
        queue.register_agent(_make_agent())
        req = _make_request()
        agent = queue.assign(req)
        assert agent is not None
        assert req.status == TransferStatus.ASSIGNED
        assert req.assigned_agent_id == "a1"
        assert "s1" in agent.active_sessions

    @pytest.mark.unit
    def test_assign_no_available_agent(self):
        queue = HandoffQueue()
        req = _make_request()
        agent = queue.assign(req)
        assert agent is None

    @pytest.mark.unit
    def test_assign_least_load(self):
        queue = HandoffQueue()
        a1 = _make_agent("a1")
        a1.active_sessions = ["s_old"]
        a2 = _make_agent("a2")
        queue.register_agent(a1)
        queue.register_agent(a2)
        req = _make_request()
        agent = queue.assign(req)
        assert agent.agent_id == "a2"  # a2 has fewer sessions

    @pytest.mark.unit
    def test_assign_agent_at_capacity(self):
        queue = HandoffQueue()
        agent = _make_agent()
        agent.max_concurrent = 1
        agent.active_sessions = ["s_old"]
        agent.status = AgentStatus.BUSY
        queue.register_agent(agent)
        req = _make_request()
        result = queue.assign(req)
        assert result is None

    @pytest.mark.unit
    def test_complete_transfer(self):
        queue = HandoffQueue()
        queue.register_agent(_make_agent())
        req = _make_request()
        queue.assign(req)
        queue.complete_transfer("s1")
        assert req.status == TransferStatus.COMPLETED
        assert req.completed_at is not None

    @pytest.mark.unit
    def test_complete_frees_agent(self):
        queue = HandoffQueue()
        agent = _make_agent()
        queue.register_agent(agent)
        queue.assign(_make_request())
        queue.complete_transfer("s1")
        assert agent.status == AgentStatus.ONLINE
        assert len(agent.active_sessions) == 0

    @pytest.mark.unit
    def test_queue_position(self):
        queue = HandoffQueue()
        queue.enqueue(_make_request("s1"))
        queue.enqueue(_make_request("s2"))
        assert queue.get_queue_position("s1") == 1
        assert queue.get_queue_position("s2") == 2
        assert queue.get_queue_position("s3") is None

    @pytest.mark.unit
    def test_queue_length(self):
        queue = HandoffQueue()
        queue.enqueue(_make_request("s1"))
        queue.enqueue(_make_request("s2"))
        assert queue.get_queue_length() == 2

    @pytest.mark.unit
    def test_estimated_wait(self):
        queue = HandoffQueue()
        queue.register_agent(_make_agent())
        queue.enqueue(_make_request("s1"))
        wait = queue.get_estimated_wait("s1")
        assert wait >= 0

    @pytest.mark.unit
    def test_estimated_wait_no_agents(self):
        queue = HandoffQueue()
        queue.enqueue(_make_request("s1"))
        wait = queue.get_estimated_wait("s1")
        assert wait > 0  # Returns timeout value

    @pytest.mark.unit
    def test_priority_ordering(self):
        queue = HandoffQueue()
        queue.enqueue(_make_request("s1", priority=1))
        queue.enqueue(_make_request("s2", priority=10))
        assert queue.get_queue_position("s2") == 1  # Higher priority first

    @pytest.mark.unit
    def test_cancel_queued(self):
        queue = HandoffQueue()
        queue.enqueue(_make_request("s1"))
        assert queue.cancel("s1") is True
        assert queue.get_queue_length() == 0

    @pytest.mark.unit
    def test_cancel_not_queued(self):
        queue = HandoffQueue()
        assert queue.cancel("nonexistent") is False

    @pytest.mark.unit
    def test_check_timeouts(self):
        queue = HandoffQueue(timeout_seconds=0)  # Instant timeout
        req = _make_request()
        req.queued_at = datetime.now(UTC) - timedelta(seconds=10)
        queue.enqueue(req)
        timed_out = queue.check_timeouts()
        assert len(timed_out) == 1
        assert timed_out[0].status == TransferStatus.TIMEOUT
        assert queue.get_queue_length() == 0

    @pytest.mark.unit
    def test_assign_removes_from_queue(self):
        queue = HandoffQueue()
        queue.register_agent(_make_agent())
        req = _make_request()
        queue.enqueue(req)
        queue.assign(req)
        assert queue.get_queue_length() == 0
