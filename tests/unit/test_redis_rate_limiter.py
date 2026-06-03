"""Tests for Redis-backed rate limiter."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from open_chat_shop.core.rate_limiter import (
    InMemoryRateLimiter,
    RateLimitGuard,
    RateLimitRule,
    RedisRateLimiter,
)


def _make_rule(**overrides):
    defaults = {"key": "user:test:messages", "window_seconds": 60, "max_requests": 30}
    defaults.update(overrides)
    return RateLimitRule(**defaults)


class TestRedisRateLimiter:
    @pytest.mark.unit
    def test_check_and_consume_allowed(self):
        """When Redis returns [1, 29], request is allowed with remaining=29."""
        redis = MagicMock()
        redis.eval.return_value = [1, 29]
        limiter = RedisRateLimiter(redis)
        rule = _make_rule()
        result = limiter.check_and_consume("user:u1:messages", rule)
        assert result.allowed
        assert result.remaining == 29
        # Verify eval was called with the Lua script
        assert redis.eval.call_count == 1

    @pytest.mark.unit
    def test_check_and_consume_over_limit(self):
        """When Redis returns [0, 0], request is blocked."""
        redis = MagicMock()
        redis.eval.return_value = [0, 0]
        limiter = RedisRateLimiter(redis)
        rule = _make_rule()
        result = limiter.check_and_consume("user:u1:messages", rule)
        assert not result.allowed
        assert result.remaining == 0

    @pytest.mark.unit
    def test_redis_failure_allows_request(self):
        """When Redis raises an exception, silently allow the request."""
        redis = MagicMock()
        redis.eval.side_effect = Exception("Connection refused")
        limiter = RedisRateLimiter(redis)
        rule = _make_rule()
        result = limiter.check_and_consume("user:u1:messages", rule)
        assert result.allowed

    @pytest.mark.unit
    def test_check_read_only(self):
        """check() is a read-only probe that does not consume."""
        redis = MagicMock()
        redis.zcard.return_value = 5
        limiter = RedisRateLimiter(redis)
        rule = _make_rule(max_requests=30)
        result = limiter.check("user:u1:messages", rule)
        assert result.allowed
        assert result.remaining == 24  # 30 - 5 - 1

    @pytest.mark.unit
    def test_consume_records_request(self):
        """consume() writes to the sorted set."""
        redis = MagicMock()
        limiter = RedisRateLimiter(redis)
        limiter.consume("user:u1:messages")
        assert redis.zadd.call_count == 1

    @pytest.mark.unit
    def test_reset_deletes_key(self):
        """reset(key) issues a Redis DEL."""
        redis = MagicMock()
        limiter = RedisRateLimiter(redis)
        limiter.reset("user:u1:messages")
        redis.delete.assert_called_once_with("user:u1:messages")

    @pytest.mark.unit
    def test_get_usage_returns_count(self):
        """get_usage prunes and returns ZCARD."""
        redis = MagicMock()
        redis.zcard.return_value = 7
        limiter = RedisRateLimiter(redis)
        count = limiter.get_usage("user:u1:messages", 60)
        assert count == 7
        redis.zremrangebyscore.assert_called_once()


class TestRateLimitGuardWithRedis:
    @pytest.mark.unit
    def test_guard_uses_redis_when_client_provided(self):
        """When redis_client is provided, Guard delegates to RedisRateLimiter."""
        redis = MagicMock()
        redis.eval.return_value = [1, 29]
        guard = RateLimitGuard(redis_client=redis)
        result = guard.check_user("user123")
        assert result.allowed
        # Redis eval should have been called (via RedisRateLimiter)
        assert redis.eval.call_count == 1

    @pytest.mark.unit
    def test_guard_uses_inmemory_when_no_redis(self):
        """When no redis_client, Guard falls back to InMemoryRateLimiter."""
        guard = RateLimitGuard()
        result = guard.check_user("user123")
        assert result.allowed
        assert isinstance(guard._limiter, InMemoryRateLimiter)

    @pytest.mark.unit
    def test_guard_explicit_limiter_without_redis(self):
        """Explicit limiter is used when redis_client is not provided."""
        limiter = InMemoryRateLimiter()
        guard = RateLimitGuard(limiter=limiter)
        assert guard._limiter is limiter

    @pytest.mark.unit
    def test_guard_redis_takes_precedence_over_explicit_limiter(self):
        """redis_client takes precedence over explicit limiter argument."""
        redis = MagicMock()
        redis.eval.return_value = [1, 29]
        limiter = InMemoryRateLimiter()
        guard = RateLimitGuard(limiter=limiter, redis_client=redis)
        assert isinstance(guard._limiter, RedisRateLimiter)
