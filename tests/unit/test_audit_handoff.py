"""Regression tests for the HANDOFF audit cluster.

Covers four verified findings in
``src/open_chat_shop/core/handoff.py`` and ``src/open_chat_shop/api/agent.py``:

- [HIGH] Every ``/api/v1/agent/*`` endpoint (not just register/status) must
  require the agent secret when one is configured. Otherwise any authenticated
  customer can read another customer's conversation history, enumerate the live
  support queue, and mutate transfer state (broken access control).
- [HIGH] ``TransferRequest.queued_at`` must be tz-aware so ``check_timeouts``
  does not raise ``TypeError`` when comparing against ``datetime.now(UTC)``.
- [LOW] The agent handoff context payload must surface the resolved intent when
  stored messages carry it (``intent`` or ``intent_name``), not silently drop it.
- [LOW] Secret comparisons must be constant-time (``hmac.compare_digest``).
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from open_chat_shop.api.agent import _secret_matches, create_agent_router
from open_chat_shop.api.app import create_app
from open_chat_shop.core.context import InMemoryContextManager
from open_chat_shop.core.handoff import (
    HandoffQueue,
    TransferRequest,
    TransferStatus,
)
from open_chat_shop.core.intent import CascadeIntentEngine, RuleBasedMatcher
from open_chat_shop.core.orchestrator import DialogueOrchestrator
from open_chat_shop.core.security import SecurityGuard
from open_chat_shop.core.strategy import RuleBasedStrategy
from open_chat_shop.core.tool import ToolInjector

AGENT_SECRET = "agent-only-secret"
WRONG_SECRET = "agent-only-secrey"  # same length, last byte differs


# ---------------------------------------------------------------------------
# Test client helpers
# ---------------------------------------------------------------------------

def _build_app_client(
    handoff_queue: HandoffQueue,
    agent_secret: str | None,
) -> TestClient:
    """Build a full-app TestClient with AGENT_SECRET wired via env."""
    orchestrator = DialogueOrchestrator(
        security_guard=SecurityGuard({}),
        context_manager=InMemoryContextManager(),
        intent_engine=CascadeIntentEngine(RuleBasedMatcher()),
        tool_injector=ToolInjector(registry={}, routing_rules=[]),
        strategy=RuleBasedStrategy(),
    )
    orchestrator.set_handoff_queue(handoff_queue)

    original = os.environ.get("AGENT_SECRET")
    if agent_secret is not None:
        os.environ["AGENT_SECRET"] = agent_secret
    else:
        os.environ.pop("AGENT_SECRET", None)
    try:
        app = create_app(orchestrator)
    finally:
        if original is not None:
            os.environ["AGENT_SECRET"] = original
        else:
            os.environ.pop("AGENT_SECRET", None)
    return TestClient(app)


def _build_router_client(
    handoff_queue: HandoffQueue,
    *,
    session_messages: dict[str, list[dict[str, object]]] | None = None,
    context_manager: object = None,
    agent_secret: str | None = None,
) -> TestClient:
    """Build a minimal TestClient mounting only the agent router.

    This bypasses the global AuthMiddleware so the assertions isolate the
    router's OWN agent-secret authorization (the bug is that the router did
    not enforce it; the middleware only proves *some* JWT/API key is valid).
    """
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(
        create_agent_router(
            handoff_queue,
            context_manager=context_manager,
            session_messages=session_messages,
            agent_secret=agent_secret,
        )
    )
    return TestClient(app)


@pytest.fixture
def handoff_queue() -> HandoffQueue:
    return HandoffQueue()


# ---------------------------------------------------------------------------
# [HIGH] Access control: every agent endpoint must require the agent secret
# ---------------------------------------------------------------------------

# Endpoints that previously had NO agent-secret check. Each is (method, path).
_PROTECTED_ENDPOINTS = [
    ("GET", "/api/v1/agent/queue"),
    ("GET", "/api/v1/agent/active"),
    ("GET", "/api/v1/agent/agents"),
    ("GET", "/api/v1/agent/history/sess-x"),
    ("POST", "/api/v1/agent/accept/sess-x"),
    ("POST", "/api/v1/agent/complete/sess-x"),
]


class TestAgentEndpointAuthorization:
    """A customer JWT is not enough; agent endpoints need the agent secret."""

    @pytest.mark.parametrize(("method", "path"), _PROTECTED_ENDPOINTS)
    def test_endpoint_rejected_without_agent_secret(
        self, handoff_queue: HandoffQueue, method: str, path: str
    ) -> None:
        # RED before fix: these returned 200/404 (handler ran) with no secret,
        # leaking history/queue or mutating transfer state. GREEN after: 401.
        client = _build_router_client(
            handoff_queue,
            session_messages={},
            agent_secret=AGENT_SECRET,
        )
        resp = client.request(method, path)
        assert resp.status_code == 401, (
            f"{method} {path} must require the agent secret"
        )
        assert "secret" in resp.json()["detail"].lower()

    @pytest.mark.parametrize(("method", "path"), _PROTECTED_ENDPOINTS)
    def test_endpoint_rejected_with_wrong_secret(
        self, handoff_queue: HandoffQueue, method: str, path: str
    ) -> None:
        client = _build_router_client(
            handoff_queue,
            session_messages={},
            agent_secret=AGENT_SECRET,
        )
        resp = client.request(
            method, path, headers={"X-Agent-Secret": WRONG_SECRET}
        )
        assert resp.status_code == 401

    def test_history_leaks_pii_without_secret_then_blocked(
        self, handoff_queue: HandoffQueue
    ) -> None:
        """Concrete PII case: another customer's history must not be readable."""
        victim_messages = {
            "victim-sess": [
                {"role": "user", "content": "我的地址是北京市朝阳区, 订单号 12345"},
            ]
        }
        client = _build_router_client(
            handoff_queue,
            session_messages=victim_messages,
            agent_secret=AGENT_SECRET,
        )
        # No agent secret -> blocked (was a full PII leak before the fix).
        blocked = client.get("/api/v1/agent/history/victim-sess")
        assert blocked.status_code == 401

        # Correct agent secret -> the real agent can fetch it.
        allowed = client.get(
            "/api/v1/agent/history/victim-sess",
            headers={"X-Agent-Secret": AGENT_SECRET},
        )
        assert allowed.status_code == 200
        assert allowed.json()["messages"] == victim_messages["victim-sess"]

    def test_endpoints_open_when_secret_not_configured(
        self, handoff_queue: HandoffQueue
    ) -> None:
        """Backward compatibility: no AGENT_SECRET => endpoints stay open."""
        client = _build_router_client(
            handoff_queue, session_messages={}, agent_secret=None
        )
        assert client.get("/api/v1/agent/queue").status_code == 200
        assert client.get("/api/v1/agent/active").status_code == 200
        assert client.get("/api/v1/agent/agents").status_code == 200
        assert client.get("/api/v1/agent/history/x").status_code == 200

    def test_protected_endpoints_pass_with_correct_secret(
        self, handoff_queue: HandoffQueue
    ) -> None:
        client = _build_router_client(
            handoff_queue, session_messages={}, agent_secret=AGENT_SECRET
        )
        hdr = {"X-Agent-Secret": AGENT_SECRET}
        assert client.get("/api/v1/agent/queue", headers=hdr).status_code == 200
        assert client.get("/api/v1/agent/active", headers=hdr).status_code == 200
        assert client.get("/api/v1/agent/agents", headers=hdr).status_code == 200
        assert (
            client.get("/api/v1/agent/history/x", headers=hdr).status_code == 200
        )


class TestEndToEndAgentAuthViaApp:
    """Same protection holds when mounted in the real app behind the middleware."""

    def test_full_app_blocks_history_without_agent_secret(
        self, handoff_queue: HandoffQueue
    ) -> None:
        client = _build_app_client(handoff_queue, agent_secret=AGENT_SECRET)
        # No middleware auth configured in this app build, so the request
        # reaches the router; the router itself must reject it (401).
        resp = client.get("/api/v1/agent/history/whatever")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# [HIGH] check_timeouts must not crash on a default-constructed request
# ---------------------------------------------------------------------------

class TestQueuedAtTimezoneAware:
    def test_default_queued_at_is_timezone_aware(self) -> None:
        req = TransferRequest(
            request_id="r1", session_id="s1", user_id="u1", reason="help"
        )
        # RED before fix: tzinfo was None (datetime.utcnow()).
        assert req.queued_at.tzinfo is not None

    def test_check_timeouts_does_not_raise_on_default_request(self) -> None:
        """The live path enqueues without passing queued_at (uses the default).

        Before the fix this raised:
        TypeError: can't subtract offset-naive and offset-aware datetimes.
        """
        queue = HandoffQueue(timeout_seconds=0)
        req = TransferRequest(
            request_id="r1", session_id="s1", user_id="u1", reason="help"
        )
        queue.enqueue(req)
        timed_out = queue.check_timeouts()  # must not raise
        assert len(timed_out) == 1
        assert timed_out[0].status == TransferStatus.TIMEOUT

    def test_check_timeouts_keeps_fresh_default_request(self) -> None:
        queue = HandoffQueue(timeout_seconds=300)
        req = TransferRequest(
            request_id="r1", session_id="s1", user_id="u1", reason="help"
        )
        queue.enqueue(req)
        assert queue.check_timeouts() == []  # default queued_at is "now"
        assert queue.get_queue_length() == 1


# ---------------------------------------------------------------------------
# [LOW] Intent context surfaces when stored messages carry it
# ---------------------------------------------------------------------------

class _StubContext:
    """Minimal stand-in for SessionContext used by accept_session."""

    def __init__(self) -> None:
        from datetime import UTC, datetime

        self.mode = None
        self.human_agent_id = None
        self.created_at = datetime.now(UTC)
        self.last_active_at = datetime.now(UTC)


class _StubContextManager:
    def __init__(self) -> None:
        self._ctx = _StubContext()

    async def load(self, _session_id: str) -> _StubContext:
        return self._ctx

    async def save(self, _ctx: object, _msg: object) -> None:
        return None


class TestIntentContextNotEmpty:
    def test_intents_populated_from_intent_key(
        self, handoff_queue: HandoffQueue
    ) -> None:
        # Register an agent so accept can assign.
        from open_chat_shop.core.handoff import HumanAgent

        handoff_queue.register_agent(HumanAgent(agent_id="a1", name="客服"))
        req = TransferRequest(
            request_id="r1", session_id="s1", user_id="u1", reason="退款"
        )
        handoff_queue.enqueue(req)

        session_messages = {
            "s1": [
                {"role": "user", "content": "我要退款", "intent": "refund"},
                {"role": "assistant", "content": "好的"},
            ]
        }
        client = _build_router_client(
            handoff_queue,
            session_messages=session_messages,
            context_manager=_StubContextManager(),
            agent_secret=None,
        )
        resp = client.post("/api/v1/agent/accept/s1")
        assert resp.status_code == 200
        intents = resp.json()["context"]["intents"]
        # Guard: the pre-existing "intent" key path still works (the old code
        # already read this key). The behavioural fix is exercised by the
        # "intent_name" test below, which was RED ([]) before the fallback.
        assert intents == ["refund"]

    def test_intents_populated_from_intent_name_key(
        self, handoff_queue: HandoffQueue
    ) -> None:
        from open_chat_shop.core.handoff import HumanAgent

        handoff_queue.register_agent(HumanAgent(agent_id="a1", name="客服"))
        req = TransferRequest(
            request_id="r1", session_id="s1", user_id="u1", reason="退款"
        )
        handoff_queue.enqueue(req)

        session_messages = {
            "s1": [
                {"role": "user", "content": "查订单", "intent_name": "order_query"},
            ]
        }
        client = _build_router_client(
            handoff_queue,
            session_messages=session_messages,
            context_manager=_StubContextManager(),
            agent_secret=None,
        )
        resp = client.post("/api/v1/agent/accept/s1")
        assert resp.status_code == 200
        assert resp.json()["context"]["intents"] == ["order_query"]


# ---------------------------------------------------------------------------
# [LOW] Constant-time secret comparison
# ---------------------------------------------------------------------------

class TestSecretMatchesConstantTime:
    def test_matches_equal(self) -> None:
        assert _secret_matches("abc", "abc") is True

    def test_rejects_different(self) -> None:
        assert _secret_matches("abc", "abd") is False

    def test_rejects_prefix(self) -> None:
        # plain == would short-circuit early on length mismatch; compare_digest
        # still returns a clean False without leaking via exceptions.
        assert _secret_matches("abc", "abcd") is False

    def test_none_treated_as_empty(self) -> None:
        assert _secret_matches(None, "abc") is False
        assert _secret_matches(None, None) is True
        assert _secret_matches("", None) is True
