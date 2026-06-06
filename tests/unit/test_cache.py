"""Tests for ResponseCache — in-memory and Redis modes."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from open_chat_shop.core.cache import _NO_CACHE_INTENTS, CACHE_TTL, ResponseCache
from open_chat_shop.core.types import AgentMessage


def _msg(text: str = "cached response") -> AgentMessage:
    return AgentMessage(
        message_type="text",
        payload={"text": text},
        text_fallback=text,
    )


class TestResponseCacheMemory:
    @pytest.mark.unit
    def test_cache_miss_returns_none(self):
        cache = ResponseCache()
        result = cache.get("search_product", {"q": "laptop"})
        assert result is None

    @pytest.mark.unit
    def test_set_then_get_returns_cached_value(self):
        cache = ResponseCache()
        msg = _msg("found laptop")
        cache.set("search_product", {"q": "laptop"}, msg)
        result = cache.get("search_product", {"q": "laptop"})
        assert result is not None
        assert result.text_fallback == "found laptop"

    @pytest.mark.unit
    def test_different_params_is_miss(self):
        cache = ResponseCache()
        msg = _msg("laptop")
        cache.set("search_product", {"q": "laptop"}, msg)
        result = cache.get("search_product", {"q": "phone"})
        assert result is None

    @pytest.mark.unit
    def test_invalidate_creates_miss(self):
        cache = ResponseCache()
        msg = _msg("laptop")
        params = {"q": "laptop"}
        cache.set("search_product", params, msg)
        assert cache.get("search_product", params) is not None
        cache.invalidate("search_product", params)
        assert cache.get("search_product", params) is None

    @pytest.mark.unit
    def test_mutable_intent_not_cached(self):
        """create_refund is a mutable operation and should never be cached."""
        cache = ResponseCache()
        msg = _msg("refund created")
        cache.set("create_refund", {"order_id": "ORD-001"}, msg)
        result = cache.get("create_refund", {"order_id": "ORD-001"})
        assert result is None

    @pytest.mark.unit
    def test_no_cache_intents_covers_expected_set(self):
        assert "create_refund" in _NO_CACHE_INTENTS
        assert "cancel_order" in _NO_CACHE_INTENTS
        assert "modify_address" in _NO_CACHE_INTENTS
        assert "handoff_to_human" in _NO_CACHE_INTENTS

    @pytest.mark.unit
    def test_cache_ttl_values(self):
        assert CACHE_TTL["search_product"] == 300
        assert CACHE_TTL["query_order"] == 60
        assert CACHE_TTL["query_logistics"] == 30


class TestResponseCacheRedis:
    @pytest.mark.unit
    def test_redis_set_and_get(self):
        redis = MagicMock()
        msg = _msg("order status")
        cache = ResponseCache(redis_client=redis)

        # Simulate set -> then get returning what was stored
        cache.set("query_order", {"order_id": "ORD-001"}, msg)
        assert redis.setex.call_count == 1

        # Simulate Redis returning the serialized data
        stored_payload = redis.setex.call_args[0][2]
        redis.get.return_value = stored_payload
        result = cache.get("query_order", {"order_id": "ORD-001"})
        assert result is not None
        assert result.text_fallback == "order status"

    @pytest.mark.unit
    def test_redis_get_returns_none_on_miss(self):
        redis = MagicMock()
        redis.get.return_value = None
        cache = ResponseCache(redis_client=redis)
        result = cache.get("query_order", {"order_id": "ORD-999"})
        assert result is None

    @pytest.mark.unit
    def test_redis_failure_returns_none(self):
        redis = MagicMock()
        redis.get.side_effect = Exception("Connection refused")
        cache = ResponseCache(redis_client=redis)
        result = cache.get("query_order", {"order_id": "ORD-001"})
        assert result is None

    @pytest.mark.unit
    def test_redis_invalidate(self):
        redis = MagicMock()
        cache = ResponseCache(redis_client=redis)
        cache.invalidate("query_order", {"order_id": "ORD-001"})
        redis.delete.assert_called_once()
