"""Tests for agent authentication via AGENT_SECRET."""
import os

import pytest
from fastapi.testclient import TestClient

from open_chat_shop.api.app import create_app
from open_chat_shop.core.context import InMemoryContextManager
from open_chat_shop.core.handoff import HandoffQueue
from open_chat_shop.core.intent import CascadeIntentEngine, RuleBasedMatcher
from open_chat_shop.core.orchestrator import DialogueOrchestrator
from open_chat_shop.core.security import SecurityGuard
from open_chat_shop.core.strategy import RuleBasedStrategy
from open_chat_shop.core.tool import ToolInjector


def _build_client(handoff_queue: HandoffQueue, agent_secret: str | None = None) -> TestClient:
    """Build a TestClient with the given agent_secret wired in."""
    orchestrator = DialogueOrchestrator(
        security_guard=SecurityGuard({}),
        context_manager=InMemoryContextManager(),
        intent_engine=CascadeIntentEngine(RuleBasedMatcher()),
        tool_injector=ToolInjector(registry={}, routing_rules=[]),
        strategy=RuleBasedStrategy(),
    )
    orchestrator.set_handoff_queue(handoff_queue)

    # Temporarily set AGENT_SECRET in the environment so create_app picks it up
    original = os.environ.get("AGENT_SECRET")
    if agent_secret is not None:
        os.environ["AGENT_SECRET"] = agent_secret
    else:
        os.environ.pop("AGENT_SECRET", None)

    try:
        app = create_app(orchestrator)
    finally:
        # Restore original env
        if original is not None:
            os.environ["AGENT_SECRET"] = original
        else:
            os.environ.pop("AGENT_SECRET", None)

    return TestClient(app)


@pytest.fixture
def handoff_queue():
    return HandoffQueue()


class TestRegisterNoSecret:
    """When AGENT_SECRET is not set, registration works as before."""

    def test_register_succeeds_without_secret(self, handoff_queue):
        client = _build_client(handoff_queue, agent_secret=None)
        resp = client.post("/api/v1/agent/register", json={
            "name": "测试客服",
            "department": "general",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["agent_id"].startswith("agent-")
        assert data["name"] == "测试客服"


class TestRegisterWithSecret:
    """When AGENT_SECRET is set, registration requires the correct secret."""

    def test_register_fails_with_wrong_secret(self, handoff_queue):
        client = _build_client(handoff_queue, agent_secret="correct-secret")
        resp = client.post("/api/v1/agent/register", json={
            "name": "客服A",
            "department": "general",
            "secret": "wrong-secret",
        })
        assert resp.status_code == 401
        assert "secret" in resp.json()["detail"].lower()

    def test_register_fails_without_secret_when_required(self, handoff_queue):
        client = _build_client(handoff_queue, agent_secret="correct-secret")
        resp = client.post("/api/v1/agent/register", json={
            "name": "客服B",
            "department": "general",
        })
        assert resp.status_code == 401

    def test_register_succeeds_with_correct_secret(self, handoff_queue):
        client = _build_client(handoff_queue, agent_secret="correct-secret")
        resp = client.post("/api/v1/agent/register", json={
            "name": "客服C",
            "department": "general",
            "secret": "correct-secret",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["agent_id"].startswith("agent-")
        assert data["name"] == "客服C"


class TestStatusUpdateAuth:
    """When AGENT_SECRET is set, status updates require X-Agent-Secret header."""

    def test_status_update_fails_without_header(self, handoff_queue):
        client = _build_client(handoff_queue, agent_secret="my-secret")
        # Register first with the correct secret
        reg = client.post("/api/v1/agent/register", json={
            "name": "客服D",
            "secret": "my-secret",
        })
        agent_id = reg.json()["agent_id"]

        # Try to update status without the header
        resp = client.put(f"/api/v1/agent/{agent_id}/status", json={"status": "offline"})
        assert resp.status_code == 401

    def test_status_update_fails_with_wrong_header(self, handoff_queue):
        client = _build_client(handoff_queue, agent_secret="my-secret")
        reg = client.post("/api/v1/agent/register", json={
            "name": "客服E",
            "secret": "my-secret",
        })
        agent_id = reg.json()["agent_id"]

        resp = client.put(
            f"/api/v1/agent/{agent_id}/status",
            json={"status": "offline"},
            headers={"X-Agent-Secret": "wrong"},
        )
        assert resp.status_code == 401

    def test_status_update_succeeds_with_correct_header(self, handoff_queue):
        client = _build_client(handoff_queue, agent_secret="my-secret")
        reg = client.post("/api/v1/agent/register", json={
            "name": "客服F",
            "secret": "my-secret",
        })
        agent_id = reg.json()["agent_id"]

        resp = client.put(
            f"/api/v1/agent/{agent_id}/status",
            json={"status": "offline"},
            headers={"X-Agent-Secret": "my-secret"},
        )
        assert resp.status_code == 200

    def test_status_update_works_without_secret_when_not_configured(self, handoff_queue):
        client = _build_client(handoff_queue, agent_secret=None)
        reg = client.post("/api/v1/agent/register", json={"name": "客服G"})
        agent_id = reg.json()["agent_id"]

        resp = client.put(
            f"/api/v1/agent/{agent_id}/status",
            json={"status": "offline"},
        )
        assert resp.status_code == 200
