"""Tests for rate limiter — sliding window and rate limit guard."""
from __future__ import annotations

import pytest

from open_chat_shop.core.rate_limiter import (
    InMemoryRateLimiter,
    RateLimitGuard,
    RateLimitRule,
)


class TestInMemoryRateLimiter:
    @pytest.mark.unit
    def test_allowed_under_limit(self):
        limiter = InMemoryRateLimiter()
        rule = RateLimitRule(key="test", window_seconds=60, max_requests=5)
        result = limiter.check_and_consume("test", rule)
        assert result.allowed

    @pytest.mark.unit
    def test_blocked_over_limit(self):
        limiter = InMemoryRateLimiter()
        rule = RateLimitRule(key="test", window_seconds=60, max_requests=3)
        for _ in range(3):
            limiter.check_and_consume("test", rule)
        result = limiter.check_and_consume("test", rule)
        assert not result.allowed

    @pytest.mark.unit
    def test_remaining_decrements(self):
        limiter = InMemoryRateLimiter()
        rule = RateLimitRule(key="test", window_seconds=60, max_requests=5)
        r1 = limiter.check_and_consume("test", rule)
        assert r1.remaining == 4
        r2 = limiter.check_and_consume("test", rule)
        assert r2.remaining == 3

    @pytest.mark.unit
    def test_independent_keys(self):
        limiter = InMemoryRateLimiter()
        rule = RateLimitRule(key="test", window_seconds=60, max_requests=1)
        r1 = limiter.check_and_consume("key_a", rule)
        r2 = limiter.check_and_consume("key_b", rule)
        assert r1.allowed
        assert r2.allowed

    @pytest.mark.unit
    def test_reset_specific_key(self):
        limiter = InMemoryRateLimiter()
        rule = RateLimitRule(key="test", window_seconds=60, max_requests=1)
        limiter.check_and_consume("key_a", rule)
        limiter.reset("key_a")
        result = limiter.check_and_consume("key_a", rule)
        assert result.allowed

    @pytest.mark.unit
    def test_reset_all(self):
        limiter = InMemoryRateLimiter()
        rule = RateLimitRule(key="test", window_seconds=60, max_requests=1)
        limiter.check_and_consume("a", rule)
        limiter.check_and_consume("b", rule)
        limiter.reset()
        assert limiter.check_and_consume("a", rule).allowed
        assert limiter.check_and_consume("b", rule).allowed

    @pytest.mark.unit
    def test_get_usage(self):
        limiter = InMemoryRateLimiter()
        rule = RateLimitRule(key="test", window_seconds=60, max_requests=10)
        limiter.check_and_consume("test", rule)
        limiter.check_and_consume("test", rule)
        assert limiter.get_usage("test", 60) == 2

    @pytest.mark.unit
    def test_retry_after_positive(self):
        limiter = InMemoryRateLimiter()
        rule = RateLimitRule(key="test", window_seconds=60, max_requests=1)
        limiter.check_and_consume("test", rule)
        result = limiter.check_and_consume("test", rule)
        assert not result.allowed
        assert result.retry_after_seconds > 0

    @pytest.mark.unit
    def test_check_without_consume(self):
        limiter = InMemoryRateLimiter()
        rule = RateLimitRule(key="test", window_seconds=60, max_requests=1)
        r1 = limiter.check("test", rule)
        assert r1.allowed
        # Check again without consuming — should still be allowed
        r2 = limiter.check("test", rule)
        assert r2.allowed


class TestRateLimitGuard:
    @pytest.mark.unit
    def test_user_under_limit(self):
        guard = RateLimitGuard()
        result = guard.check_user("user123")
        assert result.allowed

    @pytest.mark.unit
    def test_user_over_limit(self):
        limiter = InMemoryRateLimiter()
        rule = RateLimitRule(key="user:{user_id}:messages", window_seconds=60, max_requests=2)
        guard = RateLimitGuard(limiter=limiter, rules={"user_messages": rule})
        guard.check_user("u1")
        guard.check_user("u1")
        result = guard.check_user("u1")
        assert not result.allowed

    @pytest.mark.unit
    def test_ip_rate_limit(self):
        guard = RateLimitGuard()
        assert guard.check_ip("127.0.0.1").allowed

    @pytest.mark.unit
    def test_tool_rate_limit(self):
        guard = RateLimitGuard()
        assert guard.check_tool("query_order").allowed

    @pytest.mark.unit
    def test_independent_dimensions(self):
        limiter = InMemoryRateLimiter()
        rules = {
            "user_messages": RateLimitRule(
                key="user:{user_id}:msg", window_seconds=60, max_requests=1
            ),
            "ip_requests": RateLimitRule(key="ip:{ip}:req", window_seconds=60, max_requests=100),
        }
        guard = RateLimitGuard(limiter=limiter, rules=rules)
        assert guard.check_user("u1").allowed
        assert guard.check_ip("127.0.0.1").allowed
        assert not guard.check_user("u1").allowed  # user used up
        assert guard.check_ip("127.0.0.1").allowed  # ip still fine
