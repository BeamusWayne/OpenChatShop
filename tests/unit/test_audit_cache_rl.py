"""Audit regression tests — cluster CACHE_RL.

Each test encodes WHY a behaviour matters and fails on the pre-fix code:

1. CRITICAL — ResponseCache key must be scoped by user_id so one user's
   cached order/logistics card is never served to another user (a cross-tenant
   leak that bypasses the per-tool ownership check at orchestrator step 3.5).
2. HIGH — build_orchestrator with REDIS_URL set must wire a SYNCHRONOUS redis
   client into ResponseCache / RateLimitGuard. The hot methods call the client
   synchronously (redis.get / redis.eval / redis.setex); an asyncio client
   returns un-awaited coroutines that the broad excepts swallow, silently
   disabling the cache and failing the rate limiter open.
3. HIGH — the live DB engine and async redis client must be published onto
   app.state so /health/ready actually observes dependency health.
4. MEDIUM — InMemoryRateLimiter and SessionBudgetManager must bound their
   per-key dicts so a long-running process does not leak memory.
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest

from open_chat_shop.core.cache import ResponseCache
from open_chat_shop.core.cost_governance import SessionBudgetManager
from open_chat_shop.core.rate_limiter import (
    InMemoryRateLimiter,
    RateLimitRule,
)
from open_chat_shop.core.types import AgentMessage


def _msg(text: str) -> AgentMessage:
    return AgentMessage(message_type="text", payload={"text": text}, text_fallback=text)


# ---------------------------------------------------------------------------
# CRITICAL — response cache must be user-scoped
# ---------------------------------------------------------------------------


class TestCacheUserScoping:
    @pytest.mark.unit
    def test_in_memory_cache_does_not_leak_across_users(self) -> None:
        """User B must NOT read User A's cached order, even with identical params.

        Pre-fix the key hashed only intent+params, so identical params from a
        second authenticated user hit the same entry and returned A's order
        card BEFORE any ownership check ran. This is the core cross-tenant leak.
        """
        cache = ResponseCache()
        params = {"order_id": "ORD-001", "content": "查询订单ORD-001"}

        cache.set("query_order", params, _msg("A's order: addr+phone"), user_id="userA")

        # Same intent, same params, DIFFERENT caller -> must be a miss.
        assert cache.get("query_order", params, user_id="userB") is None
        # The owner still gets their own cached entry.
        a_hit = cache.get("query_order", params, user_id="userA")
        assert a_hit is not None
        assert a_hit.text_fallback == "A's order: addr+phone"

    @pytest.mark.unit
    def test_redis_cache_key_includes_user_id(self) -> None:
        """The Redis key namespace must contain the caller id so per-user
        entries cannot collide. Asserts on the key handed to setex."""
        redis = MagicMock()
        cache = ResponseCache(redis_client=redis)
        cache.set("query_order", {"order_id": "ORD-001"}, _msg("x"), user_id="userA")

        assert redis.setex.call_count == 1
        key_a = redis.setex.call_args[0][0]
        assert "userA" in key_a

        redis.reset_mock()
        cache.set("query_order", {"order_id": "ORD-001"}, _msg("y"), user_id="userB")
        key_b = redis.setex.call_args[0][0]
        assert "userB" in key_b
        assert key_a != key_b  # different users -> different Redis keys

    @pytest.mark.unit
    def test_anonymous_entries_isolated_from_named_users(self) -> None:
        """A None user_id (anonymous) must not collide with a named user."""
        cache = ResponseCache()
        params = {"q": "laptop"}
        cache.set("search_product", params, _msg("anon"), user_id=None)
        # Named user must not pick up the anonymous entry.
        assert cache.get("search_product", params, user_id="userA") is None
        # Anonymous reader still hits.
        assert cache.get("search_product", params, user_id=None) is not None


# ---------------------------------------------------------------------------
# MEDIUM — in-memory structures must be bounded
# ---------------------------------------------------------------------------


class TestRateLimiterMemoryBound:
    @pytest.mark.unit
    def test_expired_key_is_evicted_on_check(self) -> None:
        """A key whose window fully expired must be dropped, not retained
        forever as a permanent empty-list entry."""
        limiter = InMemoryRateLimiter()
        rule = RateLimitRule(key="user:u1:m", window_seconds=1, max_requests=5)
        limiter.consume("user:u1:m")
        assert "user:u1:m" in limiter._requests

        # Re-check with a window that excludes the recorded timestamp.
        import time

        time.sleep(1.05)
        limiter.check("user:u1:m", rule)
        assert "user:u1:m" not in limiter._requests

    @pytest.mark.unit
    def test_dict_is_capped_under_flood_of_distinct_keys(self) -> None:
        """Flooding with distinct stale identifiers must not grow the dict
        without bound — the sweep keeps it near the cap."""
        from open_chat_shop.core import rate_limiter as rl

        limiter = InMemoryRateLimiter()
        # Pre-load far more than the cap with timestamps in the distant past
        # so they qualify as stale.
        old = 1.0  # epoch+1s, far older than _STALE_AFTER_SECONDS
        for i in range(rl._MAX_KEYS + 500):
            limiter._requests[f"k{i}"] = [old]

        # One more consume triggers the sweep.
        limiter.consume("trigger")
        assert len(limiter._requests) <= rl._MAX_KEYS


class TestBudgetManagerMemoryBound:
    @pytest.mark.unit
    def test_sessions_dict_is_capped(self) -> None:
        """SessionBudgetManager must evict old sessions once over the cap so a
        long-lived process does not accumulate one int per session forever."""
        from open_chat_shop.core import cost_governance as cg

        mgr = SessionBudgetManager()
        for i in range(cg._MAX_SESSIONS + 200):
            mgr.consume(f"s{i}", 10)
        assert len(mgr._sessions) <= cg._MAX_SESSIONS

    @pytest.mark.unit
    def test_recently_touched_session_survives_eviction(self) -> None:
        """The session written most recently must not be the one evicted."""
        from open_chat_shop.core import cost_governance as cg

        mgr = SessionBudgetManager()
        for i in range(cg._MAX_SESSIONS + 50):
            mgr.consume(f"s{i}", 10)
        # The last-written session must still be present and accurate.
        last = f"s{cg._MAX_SESSIONS + 49}"
        assert mgr.get_status(last).used_tokens == 10


# ---------------------------------------------------------------------------
# HIGH — main.py must wire a SYNC redis client and publish infra to app.state
# ---------------------------------------------------------------------------


class TestRedisWiringIsSynchronous:
    @pytest.mark.unit
    def test_build_orchestrator_wires_sync_redis_into_cache(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With REDIS_URL set, the ResponseCache must hold a SYNC redis client.

        Pre-fix main.py passed redis.asyncio.from_url(...) — an async client —
        into ResponseCache, whose redis.get(...) is called synchronously and so
        returned a coroutine that the broad except swallowed: the cache was
        always a miss. This asserts the wired client is the synchronous type.
        """
        import redis as redis_sync_mod
        import redis.asyncio as aioredis

        monkeypatch.setenv("DEV_MODE", "true")
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
        monkeypatch.delenv("DATABASE_URL", raising=False)

        resources: dict[str, object] = {}
        import main as main_mod

        orch = main_mod.build_orchestrator(resources)

        client = orch._response_cache._redis
        assert client is not None
        # The cache client must be a SYNC client, never the asyncio one.
        assert isinstance(client, redis_sync_mod.Redis)
        assert not isinstance(client, aioredis.Redis)
        # resources must expose both clients for app.state publishing.
        assert isinstance(resources.get("redis_sync"), redis_sync_mod.Redis)
        assert isinstance(resources.get("redis_async"), aioredis.Redis)

    @pytest.mark.unit
    def test_no_redis_url_leaves_in_memory_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without REDIS_URL the cache stays in-memory (redis client is None)."""
        monkeypatch.setenv("DEV_MODE", "true")
        monkeypatch.delenv("REDIS_URL", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)

        resources: dict[str, object] = {}
        import main as main_mod

        orch = main_mod.build_orchestrator(resources)
        assert orch._response_cache._redis is None


class TestReadinessProbeObservesRealHealth:
    @pytest.mark.unit
    def test_real_db_engine_is_published_on_app_state(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: object
    ) -> None:
        """With a real DATABASE_URL, create_main_app must publish the live
        engine onto app.state so the readiness probe can query it.

        Pre-fix NOTHING ever set app.state.db_engine — the engine lived only as
        a local in _build_repositories — so _check_database short-circuited to
        "ok" and /health/ready could never report a DB outage. This asserts the
        wiring now publishes the engine during lifespan startup.
        """
        from fastapi.testclient import TestClient

        db_file = os.path.join(str(tmp_path), "ready.db")  # type: ignore[arg-type]
        monkeypatch.setenv("DEV_MODE", "true")
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
        monkeypatch.delenv("REDIS_URL", raising=False)

        import main as main_mod

        app = main_mod.create_main_app()
        with TestClient(app):  # entering runs lifespan startup
            assert getattr(app.state, "db_engine", None) is not None
            # A healthy sqlite engine -> readiness is ok and queries the engine.
            resp = TestClient(app).get("/health/ready")
            assert resp.status_code == 200
            assert resp.json()["checks"]["database"]["status"] == "ok"

    @pytest.mark.unit
    def test_failing_engine_makes_ready_return_503(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When app.state.db_engine is a failing engine, /health/ready must 503.

        Guards the gate itself: a published-but-unreachable engine trips the
        readiness gate instead of being reported healthy.
        """
        from fastapi.testclient import TestClient

        monkeypatch.setenv("DEV_MODE", "true")
        monkeypatch.delenv("REDIS_URL", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)

        import main as main_mod

        app = main_mod.create_main_app()

        class _BrokenEngine:
            def connect(self) -> object:
                raise RuntimeError("db down")

            def dispose(self) -> None:
                pass

        with TestClient(app) as client:
            # Simulate the published engine becoming unreachable at runtime.
            app.state.db_engine = _BrokenEngine()
            resp = client.get("/health/ready")
            assert resp.status_code == 503
