"""Tests for RedisContextManager with mocked Redis client."""
from __future__ import annotations

import json
import pytest

from open_chat_shop.core.types import Message, SessionContext, AgentMessage, SessionMode
from open_chat_shop.storage.redis_context import (
    RedisContextManager,
    _serialize_context,
    _deserialize_context,
)
from open_chat_shop.core.exceptions import ContextError


def _make_ctx(**overrides) -> SessionContext:
    from datetime import datetime
    defaults = dict(
        session_id="s1",
        user_id="u1",
        channel="web",
        history=[],
        slots={},
        fsm_state="idle",
        token_usage=0,
        user_role="customer",
        created_at=datetime(2026, 1, 1),
        last_active_at=datetime(2026, 1, 1),
    )
    defaults.update(overrides)
    return SessionContext(**defaults)


class FakeRedis:
    """In-memory fake Redis for unit testing."""

    def __init__(self) -> None:
        self._store: dict[str, dict[str, str]] = {}
        self._ttls: dict[str, int] = {}

    async def hgetall(self, key: str) -> dict[str, str]:
        return dict(self._store.get(key, {}))

    async def hset(self, key: str, mapping: dict[str, str]) -> None:
        if key not in self._store:
            self._store[key] = {}
        self._store[key].update(mapping)

    async def expire(self, key: str, seconds: int) -> None:
        self._ttls[key] = seconds

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)


# ===========================================================================
# Serialization round-trip
# ===========================================================================


class TestSerialization:
    @pytest.mark.unit
    def test_roundtrip_empty_context(self):
        ctx = _make_ctx()
        serialized = _serialize_context(ctx)
        restored = _deserialize_context(serialized)
        assert restored.session_id == ctx.session_id
        assert restored.user_id == ctx.user_id
        assert restored.channel == ctx.channel
        assert restored.history == []
        assert restored.slots == {}

    @pytest.mark.unit
    def test_roundtrip_with_history(self):
        ctx = _make_ctx(history=[
            Message(role="user", content="hello"),
            Message(role="assistant", content="hi there"),
        ])
        serialized = _serialize_context(ctx)
        restored = _deserialize_context(serialized)
        assert len(restored.history) == 2
        assert restored.history[0].role == "user"
        assert restored.history[0].content == "hello"
        assert restored.history[1].role == "assistant"

    @pytest.mark.unit
    def test_roundtrip_with_slots(self):
        ctx = _make_ctx(slots={"order_id": "ORD-123", "category": "electronics"})
        serialized = _serialize_context(ctx)
        restored = _deserialize_context(serialized)
        assert restored.slots["order_id"] == "ORD-123"
        assert restored.slots["category"] == "electronics"

    @pytest.mark.unit
    def test_roundtrip_fsm_state(self):
        ctx = _make_ctx(fsm_state="processing", current_scenario="refund")
        serialized = _serialize_context(ctx)
        restored = _deserialize_context(serialized)
        assert restored.fsm_state == "processing"
        assert restored.current_scenario == "refund"

    @pytest.mark.unit
    def test_roundtrip_token_usage(self):
        ctx = _make_ctx(token_usage=5000)
        serialized = _serialize_context(ctx)
        restored = _deserialize_context(serialized)
        assert restored.token_usage == 5000

    @pytest.mark.unit
    def test_null_fields_handled(self):
        ctx = _make_ctx(user_id=None, summary=None, current_scenario=None)
        serialized = _serialize_context(ctx)
        restored = _deserialize_context(serialized)
        assert restored.user_id is None
        assert restored.summary is None
        assert restored.current_scenario is None


# ===========================================================================
# RedisContextManager
# ===========================================================================


class TestRedisContextManager:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_load_creates_new_session(self):
        redis = FakeRedis()
        mgr = RedisContextManager(redis, ttl_seconds=1800)

        ctx = await mgr.load("new-session")

        assert ctx.session_id == "new-session"
        assert ctx.history == []
        assert ctx.fsm_state == "idle"
        assert "session:new-session" in redis._store

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_load_existing_session(self):
        redis = FakeRedis()
        original = _make_ctx(session_id="s1", user_id="u1", token_usage=100)
        await redis.hset("session:s1", mapping=_serialize_context(original))

        mgr = RedisContextManager(redis, ttl_seconds=1800)
        ctx = await mgr.load("s1")

        assert ctx.session_id == "s1"
        assert ctx.user_id == "u1"
        assert ctx.token_usage == 100

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_save_persists_to_redis(self):
        redis = FakeRedis()
        mgr = RedisContextManager(redis, ttl_seconds=600)

        ctx = _make_ctx(session_id="s1")
        response = AgentMessage(
            message_type="text",
            payload={"content": "hello"},
            text_fallback="hello",
        )
        await mgr.save(ctx, response)

        assert "session:s1" in redis._store
        assert redis._ttls["session:s1"] == 600

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_load_save_roundtrip(self):
        redis = FakeRedis()
        mgr = RedisContextManager(redis)

        # Load creates new
        ctx = await mgr.load("s1")
        ctx_with_slots = SessionContext(
            **{**ctx.__dict__, "slots": {"order_id": "ORD-456"}}
        )
        response = AgentMessage(
            message_type="text", payload={"content": "ok"}, text_fallback="ok",
        )
        await mgr.save(ctx_with_slots, response)

        # Load again should have the slots
        loaded = await mgr.load("s1")
        assert loaded.slots["order_id"] == "ORD-456"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_compress_reduces_history(self):
        redis = FakeRedis()
        mgr = RedisContextManager(redis, max_context_tokens=100)

        history = [Message(role="user", content=f"message {i} " * 20) for i in range(10)]
        ctx = _make_ctx(history=history)

        compressed = await mgr.compress(ctx)
        assert len(compressed.history) < len(history)
        assert compressed.summary is not None
        assert "compressed" in compressed.summary

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_compress_no_op_when_under_budget(self):
        redis = FakeRedis()
        mgr = RedisContextManager(redis, max_context_tokens=100_000)

        ctx = _make_ctx(history=[Message(role="user", content="short")])
        compressed = await mgr.compress(ctx)
        assert len(compressed.history) == 1

    @pytest.mark.unit
    def test_get_token_budget(self):
        redis = FakeRedis()
        mgr = RedisContextManager(redis, max_context_tokens=4096)
        ctx = _make_ctx()

        budget = mgr.get_token_budget(ctx)
        assert budget.total == 4096
        assert budget.system_prompt == 819  # 20%
        assert budget.history == 2048  # 50%

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_update_slots_returns_new_context(self):
        redis = FakeRedis()
        mgr = RedisContextManager(redis)
        ctx = _make_ctx(slots={"a": "1"})

        updated = await mgr.update_slots(ctx, {"b": "2"})

        assert updated.slots == {"a": "1", "b": "2"}
        assert ctx.slots == {"a": "1"}  # original unchanged

    @pytest.mark.unit
    def test_roundtrip_preserves_mode_and_human_agent_id(self):
        """Regression: mode and human_agent_id must survive serialize→deserialize."""
        ctx = _make_ctx(
            mode=SessionMode.HUMAN_MODE,
            human_agent_id="agent-7",
        )
        serialized = _serialize_context(ctx)
        restored = _deserialize_context(serialized)
        assert restored.mode == SessionMode.HUMAN_MODE
        assert restored.human_agent_id == "agent-7"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_save_load_preserves_mode_and_human_agent_id(self):
        """Regression: mode=HUMAN_MODE and human_agent_id survive a full save→load cycle."""
        redis = FakeRedis()
        mgr = RedisContextManager(redis)

        ctx = _make_ctx(mode=SessionMode.HUMAN_MODE, human_agent_id="agent-7")
        response = AgentMessage(
            message_type="text", payload={"content": "ok"}, text_fallback="ok",
        )
        await mgr.save(ctx, response)

        loaded = await mgr.load("s1")
        assert loaded.mode == SessionMode.HUMAN_MODE
        assert loaded.human_agent_id == "agent-7"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_redis_error_raises_context_error(self):
        class FailingRedis(FakeRedis):
            async def hgetall(self, key):
                raise ConnectionError("Redis down")

        redis = FailingRedis()
        mgr = RedisContextManager(redis)

        with pytest.raises(ContextError, match="Failed to load"):
            await mgr.load("s1")
