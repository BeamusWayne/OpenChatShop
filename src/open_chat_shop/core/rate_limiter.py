"""Rate limiting with sliding window algorithm.

Supports per-user, per-IP, and per-tool rate limiting using
in-memory counters. For production, replace with Redis-backed
implementation using Sorted Sets.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import logging

logger = logging.getLogger(__name__)


@dataclass
class RateLimitRule:
    """A single rate limit rule."""
    key: str  # e.g. "user:{id}:messages", "ip:{addr}:requests"
    window_seconds: int
    max_requests: int


@dataclass
class RateLimitResult:
    """Result of a rate limit check."""
    allowed: bool
    remaining: int
    reset_at: float  # Unix timestamp when the window resets
    retry_after_seconds: float = 0.0


class InMemoryRateLimiter:
    """In-memory sliding window rate limiter.

    Uses a list of timestamps per key. Old entries outside
    the window are pruned on each check.
    """

    def __init__(self) -> None:
        self._requests: dict[str, list[float]] = {}

    def check(self, key: str, rule: RateLimitRule) -> RateLimitResult:
        """Check if a request is allowed under the rate limit.

        Does NOT consume the request. Call `consume` to record it.
        """
        now = time.time()
        window_start = now - rule.window_seconds
        requests = self._requests.get(key, [])
        # Prune old entries
        current = [t for t in requests if t > window_start]
        count = len(current)
        remaining = max(0, rule.max_requests - count)
        # Find when the oldest request in window expires
        if current:
            reset_at = current[0] + rule.window_seconds
        else:
            reset_at = now + rule.window_seconds

        if count >= rule.max_requests:
            retry_after = reset_at - now
            return RateLimitResult(
                allowed=False,
                remaining=0,
                reset_at=reset_at,
                retry_after_seconds=max(0.1, retry_after),
            )

        return RateLimitResult(
            allowed=True,
            remaining=remaining - 1,  # -1 because consume will add one
            reset_at=reset_at,
        )

    def consume(self, key: str) -> None:
        """Record a request for rate limiting."""
        now = time.time()
        if key not in self._requests:
            self._requests[key] = []
        self._requests[key].append(now)

    def check_and_consume(self, key: str, rule: RateLimitRule) -> RateLimitResult:
        """Check rate limit and consume if allowed. Atomic operation."""
        result = self.check(key, rule)
        if result.allowed:
            self.consume(key)
        return result

    def reset(self, key: str | None = None) -> None:
        """Reset rate limit for a key or all keys."""
        if key is None:
            self._requests.clear()
        else:
            self._requests.pop(key, None)

    def get_usage(self, key: str, window_seconds: int) -> int:
        """Get current request count for a key within a window."""
        now = time.time()
        requests = self._requests.get(key, [])
        return len([t for t in requests if t > now - window_seconds])


# Pre-defined rate limit rules
DEFAULT_RULES = {
    "user_messages": RateLimitRule(
        key="user:{user_id}:messages",
        window_seconds=60,
        max_requests=30,
    ),
    "ip_requests": RateLimitRule(
        key="ip:{ip}:requests",
        window_seconds=60,
        max_requests=60,
    ),
    "tool_calls": RateLimitRule(
        key="tool:{tool_name}:calls",
        window_seconds=3600,
        max_requests=1000,
    ),
}


class RateLimitGuard:
    """Apply rate limits to requests using configurable rules."""

    def __init__(
        self,
        limiter: InMemoryRateLimiter | None = None,
        rules: dict[str, RateLimitRule] | None = None,
    ) -> None:
        self._limiter = limiter or InMemoryRateLimiter()
        self._rules = rules or DEFAULT_RULES

    def check_user(self, user_id: str) -> RateLimitResult:
        """Check user message rate limit."""
        rule = self._rules["user_messages"]
        key = rule.key.replace("{user_id}", user_id)
        return self._limiter.check_and_consume(key, rule)

    def check_ip(self, ip: str) -> RateLimitResult:
        """Check IP request rate limit."""
        rule = self._rules["ip_requests"]
        key = rule.key.replace("{ip}", ip)
        return self._limiter.check_and_consume(key, rule)

    def check_tool(self, tool_name: str) -> RateLimitResult:
        """Check tool call rate limit."""
        rule = self._rules["tool_calls"]
        key = rule.key.replace("{tool_name}", tool_name)
        return self._limiter.check_and_consume(key, rule)

    def reset(self, key_type: str, identifier: str) -> None:
        """Reset rate limit for a specific key."""
        rule = self._rules.get(key_type)
        if rule:
            key = rule.key.replace(f"{{{key_type}}}", identifier)
            self._limiter.reset(key)
