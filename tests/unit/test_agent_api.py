"""Tests for Agent API endpoints."""

import pytest
from fastapi.testclient import TestClient

from open_chat_shop.api.app import create_app
from open_chat_shop.core.context import InMemoryContextManager
from open_chat_shop.core.handoff import HandoffQueue, TransferRequest
from open_chat_shop.core.intent import CascadeIntentEngine, RuleBasedMatcher
from open_chat_shop.core.orchestrator import DialogueOrchestrator
from open_chat_shop.core.security import SecurityGuard
from open_chat_shop.core.strategy import RuleBasedStrategy
from open_chat_shop.core.tool import ToolInjector


@pytest.fixture
def handoff_queue():
    return HandoffQueue()


@pytest.fixture
def agent_client(handoff_queue):
    """Create a test client with agent router wired in."""
    orchestrator = DialogueOrchestrator(
        security_guard=SecurityGuard({}),
        context_manager=InMemoryContextManager(),
        intent_engine=CascadeIntentEngine(RuleBasedMatcher()),
        tool_injector=ToolInjector(registry={}, routing_rules=[]),
        strategy=RuleBasedStrategy(),
    )
    orchestrator.set_handoff_queue(handoff_queue)
    app = create_app(orchestrator)
    return TestClient(app)


class TestAgentRegister:
    def test_register_returns_agent_id(self, agent_client):
        resp = agent_client.post("/api/v1/agent/register", json={
            "name": "测试客服",
            "department": "general",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["agent_id"].startswith("agent-")
        assert data["name"] == "测试客服"
        assert data["department"] == "general"

    def test_register_default_department(self, agent_client):
        resp = agent_client.post("/api/v1/agent/register", json={"name": "小李"})
        assert resp.status_code == 200
        assert resp.json()["department"] == "general"


class TestAgentList:
    def test_list_agents_empty(self, agent_client):
        resp = agent_client.get("/api/v1/agent/agents")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_agents_after_register(self, agent_client):
        agent_client.post("/api/v1/agent/register", json={"name": "客服A"})
        resp = agent_client.get("/api/v1/agent/agents")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "客服A"
        assert data[0]["status"] == "online"


class TestAgentStatus:
    def test_update_status_offline(self, agent_client, handoff_queue):
        reg = agent_client.post("/api/v1/agent/register", json={"name": "客服B"}).json()
        resp = agent_client.put(f"/api/v1/agent/{reg['agent_id']}/status", json={"status": "offline"})
        assert resp.status_code == 200
        agent = handoff_queue._agents[reg["agent_id"]]
        assert agent.status.value == "offline"

    def test_update_status_nonexistent_agent(self, agent_client):
        resp = agent_client.put("/api/v1/agent/nonexistent/status", json={"status": "offline"})
        assert resp.status_code == 404

    def test_update_status_invalid(self, agent_client):
        reg = agent_client.post("/api/v1/agent/register", json={"name": "客服C"}).json()
        resp = agent_client.put(f"/api/v1/agent/{reg['agent_id']}/status", json={"status": "invalid"})
        assert resp.status_code == 400


class TestQueueManagement:
    def test_empty_queue(self, agent_client):
        resp = agent_client.get("/api/v1/agent/queue")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_queue_with_items(self, agent_client, handoff_queue):
        req = TransferRequest(
            request_id="tr-001",
            session_id="sess-001",
            user_id="user-001",
            reason="需要退款帮助",
        )
        handoff_queue.enqueue(req)
        resp = agent_client.get("/api/v1/agent/queue")
        data = resp.json()
        assert len(data) == 1
        assert data[0]["session_id"] == "sess-001"
        assert data[0]["reason"] == "需要退款帮助"
        assert data[0]["position"] == 1

    def test_empty_active(self, agent_client):
        resp = agent_client.get("/api/v1/agent/active")
        assert resp.status_code == 200
        assert resp.json() == []


class TestAcceptSession:
    def test_accept_success(self, agent_client, handoff_queue):
        agent_client.post("/api/v1/agent/register", json={"name": "客服D"})
        req = TransferRequest(
            request_id="tr-002",
            session_id="sess-002",
            user_id="user-002",
            reason="转人工",
        )
        handoff_queue.enqueue(req)
        resp = agent_client.post("/api/v1/agent/accept/sess-002")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "assigned"
        assert data["session_id"] == "sess-002"
        assert data["agent_name"] == "客服D"

    def test_accept_nonexistent_session(self, agent_client):
        resp = agent_client.post("/api/v1/agent/accept/nonexistent")
        assert resp.status_code == 404


class TestCompleteSession:
    def test_complete_success(self, agent_client, handoff_queue):
        agent_client.post("/api/v1/agent/register", json={"name": "客服E"})
        req = TransferRequest(
            request_id="tr-003",
            session_id="sess-003",
            user_id="user-003",
            reason="help",
        )
        handoff_queue.enqueue(req)
        agent_client.post("/api/v1/agent/accept/sess-003")
        resp = agent_client.post("/api/v1/agent/complete/sess-003")
        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"

    def test_complete_nonexistent_session(self, agent_client):
        resp = agent_client.post("/api/v1/agent/complete/nonexistent")
        assert resp.status_code == 404
