"""Response cache for read-only query intents.

Caches AgentMessage responses by intent + parameter hash, using either
an in-memory dict (default) or Redis. Mutable operations (refunds,
cancellations, etc.) are never cached.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import time
from typing import Any

from open_chat_shop.core.types import AgentMessage

logger = logging.getLogger(__name__)

# TTL per intent (seconds)
CACHE_TTL: dict[str, int] = {
    "search_product": 300,
    "query_order": 60,
    "query_logistics": 30,
}

# Mutable operations — never cache these
_NO_CACHE_INTENTS: frozenset[str] = frozenset(
    {"create_refund", "cancel_order", "modify_address", "handoff_to_human"}
)


class ResponseCache:
    """Cache AgentMessage responses keyed by intent and params.

    Supports an optional Redis client for distributed caching. Falls
    back to an in-memory dict when no Redis is provided.
    """

    def __init__(self, redis_client: Any | None = None) -> None:
        self._redis = redis_client
        self._memory: dict[str, tuple[float, AgentMessage]] = {}

    def _make_key(self, intent: str, params: dict[str, Any]) -> str:
        h = hashlib.md5(json.dumps(params, sort_keys=True, default=str).encode()).hexdigest()
        return f"cache:{intent}:{h}"

    def get(self, intent: str, params: dict[str, Any]) -> AgentMessage | None:
        """Retrieve a cached response, or None on miss / expired entry."""
        if intent in _NO_CACHE_INTENTS:
            return None
        key = self._make_key(intent, params)
        if self._redis:
            return self._get_redis(key)
        return self._get_memory(key)

    def set(
        self,
        intent: str,
        params: dict[str, Any],
        response: AgentMessage,
        ttl: int | None = None,
    ) -> None:
        """Store a response in cache. No-op for mutable intents or zero TTL."""
        if intent in _NO_CACHE_INTENTS:
            return
        ttl = ttl or CACHE_TTL.get(intent, 0)
        if ttl <= 0:
            return
        key = self._make_key(intent, params)
        if self._redis:
            self._set_redis(key, response, ttl)
            return
        self._memory[key] = (time.monotonic() + ttl, response)

    def invalidate(self, intent: str, params: dict[str, Any]) -> None:
        """Remove a specific cached entry."""
        key = self._make_key(intent, params)
        self._memory.pop(key, None)
        if self._redis:
            with contextlib.suppress(Exception):
                self._redis.delete(key)

    # -- internal helpers ---------------------------------------------------

    def _get_memory(self, key: str) -> AgentMessage | None:
        entry = self._memory.get(key)
        if not entry:
            return None
        expires, msg = entry
        if time.monotonic() > expires:
            self._memory.pop(key, None)
            return None
        return msg

    def _get_redis(self, key: str) -> AgentMessage | None:
        try:
            raw = self._redis.get(key)
        except Exception:
            return None
        if raw is None:
            return None
        try:
            data = json.loads(raw)
            return AgentMessage(**data)
        except Exception:
            logger.warning("Failed to deserialize cached response", exc_info=True)
            return None

    def _set_redis(self, key: str, response: AgentMessage, ttl: int) -> None:
        try:
            payload = json.dumps(
                {
                    "message_type": response.message_type,
                    "payload": response.payload,
                    "text_fallback": response.text_fallback,
                    "suggestions": response.suggestions,
                    "requires_confirmation": response.requires_confirmation,
                }
            )
            self._redis.setex(key, ttl, payload)
        except Exception:
            logger.warning("Failed to write response cache to Redis", exc_info=True)
