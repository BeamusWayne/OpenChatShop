
# orchestrator (test_audit_<CLUSTER>.py, CLUSTER=STORAGE); keep the uppercase name.
"""Regression tests for the STORAGE audit cluster.

Each test encodes *why* the fixed behavior matters and fails against the
pre-fix implementation:

* HIGH  — DatabaseContextManager dropped user turns, never compacted, and grew
          history rows without bound across saves.
* LOW   — Database-backed sessions hardcoded ``tokens_used=0``, so the
          recovered ``token_usage`` was permanently 0.
* MEDIUM— ``load``/``save`` ran synchronous SQLModel sessions inside ``async
          def`` directly on the event loop (no thread offload).
* C2     — A synchronous ``get(session_id)`` must exist on the ContextManager
          ABC and on the Redis/DB managers, backed by a write-through cache.
"""
from __future__ import annotations

import asyncio
import inspect
from datetime import UTC, datetime, timedelta

import pytest

from open_chat_shop.core.context import ContextManager
from open_chat_shop.core.types import (
    AgentMessage,
    Message,
    SessionContext,
    SessionMode,
)
from open_chat_shop.storage.db_context import DatabaseContextManager
from open_chat_shop.storage.redis_context import RedisContextManager


def _reply(text: str = "ok", *, tokens: int | None = None) -> AgentMessage:
    meta = {"token_usage": tokens} if tokens is not None else {}
    return AgentMessage(
        message_type="text",
        payload={"content": text},
        text_fallback=text,
        meta=meta,
    )


def _ctx(session_id: str = "s1", **overrides) -> SessionContext:
    now = datetime.now(UTC)
    defaults = dict(
        session_id=session_id,
        user_id="u1",
        channel="web",
        history=[],
        created_at=now,
        last_active_at=now,
    )
    defaults.update(overrides)
    return SessionContext(**defaults)  # type: ignore[arg-type]


class FakeRedis:
    """Minimal async fake Redis sufficient for RedisContextManager."""

    def __init__(self) -> None:
        self._store: dict[str, dict[str, str]] = {}
        self._ttls: dict[str, int] = {}

    async def hgetall(self, key: str) -> dict[str, str]:
        return dict(self._store.get(key, {}))

    async def hset(self, key: str, mapping: dict[str, str]) -> None:
        self._store.setdefault(key, {}).update(mapping)

    async def expire(self, key: str, seconds: int) -> None:
        self._ttls[key] = seconds


# ===========================================================================
# HIGH — user turns persist, compaction shrinks storage, no unbounded growth
# ===========================================================================


class TestDatabaseHistoryRoundTrip:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_user_turns_in_history_survive_save_and_load(self):
        """User messages in context.history must round-trip.

        Pre-fix save() ignored context.history entirely and only wrote an
        assistant row, so reloaded history was one-sided (user turns lost).
        """
        mgr = DatabaseContextManager(db_url="sqlite:///:memory:")
        base = datetime.now(UTC)
        ctx = _ctx(
            history=[
                Message(role="user", content="我想退货", timestamp=base),
                Message(
                    role="assistant",
                    content="好的，请提供订单号",
                    timestamp=base + timedelta(seconds=1),
                ),
            ],
        )
        await mgr.save(ctx, _reply("订单号是？"))

        loaded = await mgr.load("s1")
        roles = [m.role for m in loaded.history]
        contents = [m.content for m in loaded.history]
        # Both prior turns (user + assistant) plus the new assistant reply.
        assert "user" in roles, "user turn was dropped on persistence"
        assert contents[:2] == ["我想退货", "好的，请提供订单号"]
        assert contents[-1] == "订单号是？"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_repeated_saves_do_not_grow_history_unbounded(self):
        """Re-saving the same context must not accumulate duplicate rows.

        Pre-fix save() appended a NEW assistant row every turn and never
        pruned, so load() re-read an ever-growing history. With reconciliation,
        persisted history mirrors context.history + 1 assistant reply.
        """
        mgr = DatabaseContextManager(db_url="sqlite:///:memory:")
        ctx = _ctx(history=[Message(role="user", content="hi")])

        for _ in range(5):
            await mgr.save(ctx, _reply("hello"))

        loaded = await mgr.load("s1")
        # Exactly the one history message + one assistant reply, not 5 replies.
        assert len(loaded.history) == 2, (
            f"history grew unbounded across saves: {[m.content for m in loaded.history]}"
        )

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_compaction_shrinks_persisted_history(self):
        """After compaction, save persists only the kept window.

        Pre-fix, compress() trimmed the in-memory list but save() discarded it
        and load() re-read every assistant row ever written, so compaction
        never shrank storage.
        """
        mgr = DatabaseContextManager(db_url="sqlite:///:memory:")
        base = datetime.now(UTC)
        long_history = [
            Message(
                role="user" if i % 2 == 0 else "assistant",
                content=f"turn {i}",
                timestamp=base + timedelta(seconds=i),
            )
            for i in range(40)
        ]
        await mgr.save(_ctx(history=long_history), _reply("latest"))
        before = await mgr.load("s1")
        assert len(before.history) == 41  # 40 + assistant reply

        # Now persist a compacted context (only the last few turns kept).
        compacted = _ctx(history=long_history[-4:])
        await mgr.save(compacted, _reply("after-compaction"))

        after = await mgr.load("s1")
        assert len(after.history) == 5, (
            "compaction did not shrink persisted history"
        )
        assert after.history[-1].content == "after-compaction"


# ===========================================================================
# LOW — real token usage is persisted and recovered (not hardcoded 0)
# ===========================================================================


class TestDatabaseTokenUsage:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_token_usage_persists_from_response_meta(self):
        """save() must record response.meta['token_usage'] and recover it.

        Pre-fix the assistant row was written with tokens_used=0, so the
        reloaded context.token_usage was permanently 0.
        """
        mgr = DatabaseContextManager(db_url="sqlite:///:memory:")
        await mgr.save(_ctx(), _reply("answer", tokens=137))

        loaded = await mgr.load("s1")
        assert loaded.token_usage == 137

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_token_usage_accumulates_across_turns(self):
        """Cumulative token usage survives multiple save/load cycles."""
        mgr = DatabaseContextManager(db_url="sqlite:///:memory:")
        await mgr.save(_ctx(), _reply("a", tokens=100))
        ctx2 = await mgr.load("s1")
        assert ctx2.token_usage == 100

        await mgr.save(ctx2, _reply("b", tokens=50))
        ctx3 = await mgr.load("s1")
        assert ctx3.token_usage == 150


# ===========================================================================
# MEDIUM — sync DB work is offloaded off the event loop
# ===========================================================================


class TestDatabaseEventLoopOffload:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_load_and_save_offload_to_thread(self, monkeypatch):
        """load()/save() must run the blocking DB work via asyncio.to_thread.

        Pre-fix they executed the synchronous SQLModel session directly on the
        event loop thread, stalling all other coroutines for the query
        duration. We assert the offload happens by spying on to_thread.
        """
        mgr = DatabaseContextManager(db_url="sqlite:///:memory:")
        calls: list[str] = []
        real_to_thread = asyncio.to_thread

        async def spy_to_thread(func, /, *args, **kwargs):
            calls.append(getattr(func, "__name__", repr(func)))
            return await real_to_thread(func, *args, **kwargs)

        monkeypatch.setattr(asyncio, "to_thread", spy_to_thread)

        await mgr.load("s1")
        await mgr.save(_ctx(), _reply("x"))

        assert "_load_sync" in calls
        assert "_save_sync" in calls


# ===========================================================================
# C2 — synchronous get() on the ABC and both production managers
# ===========================================================================


class TestSyncGetContract:
    @pytest.mark.unit
    def test_abc_declares_sync_get(self):
        get_attr = ContextManager.__dict__.get("get")
        assert get_attr is not None, "ContextManager ABC must declare get()"
        assert getattr(get_attr, "__isabstractmethod__", False), (
            "ContextManager.get must be an abstractmethod"
        )
        # Must be a *sync* method so API guards can call it without awaiting.
        assert not inspect.iscoroutinefunction(get_attr)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_db_get_is_write_through_cache(self):
        mgr = DatabaseContextManager(db_url="sqlite:///:memory:")
        assert mgr.get("s1") is None  # not loaded yet

        await mgr.load("s1")
        cached = mgr.get("s1")
        assert cached is not None
        assert cached.session_id == "s1"
        assert not inspect.iscoroutinefunction(type(mgr).get)

        # save() refreshes the cache with the persisted assistant turn.
        await mgr.save(_ctx(), _reply("hello-cache"))
        after = mgr.get("s1")
        assert after is not None
        assert after.history[-1].content == "hello-cache"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_redis_get_is_write_through_cache(self):
        mgr = RedisContextManager(FakeRedis())
        assert mgr.get("s1") is None  # not loaded yet

        await mgr.load("s1")
        cached = mgr.get("s1")
        assert cached is not None
        assert cached.session_id == "s1"
        assert not inspect.iscoroutinefunction(type(mgr).get)

        ctx = _ctx(mode=SessionMode.HUMAN_MODE, human_agent_id="agent-9")
        await mgr.save(ctx, _reply("ok"))
        after = mgr.get("s1")
        assert after is not None
        assert after.mode == SessionMode.HUMAN_MODE
        assert after.human_agent_id == "agent-9"
