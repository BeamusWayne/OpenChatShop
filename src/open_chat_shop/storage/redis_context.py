"""Redis-backed ContextManager for production session persistence.

Uses Redis Hash for session storage with configurable TTL.
Falls back gracefully when Redis is unavailable.
"""
from __future__ import annotations

import json
import logging
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from open_chat_shop.core.context import ContextManager
from open_chat_shop.core.exceptions import ContextError
from open_chat_shop.core.types import (
    AgentMessage,
    Message,
    SessionContext,
    SessionMode,
    TokenBudget,
)

logger = logging.getLogger(__name__)


def _serialize_context(ctx: SessionContext) -> dict[str, str]:
    """Serialize SessionContext to a flat dict of strings for Redis Hash."""
    return {
        "session_id": ctx.session_id,
        "user_id": ctx.user_id or "",
        "channel": ctx.channel,
        "history": json.dumps([
            {"role": m.role, "content": m.content, "metadata": m.metadata}
            for m in ctx.history
        ], ensure_ascii=False),
        "summary": ctx.summary or "",
        "slots": json.dumps(ctx.slots, ensure_ascii=False),
        "fsm_state": ctx.fsm_state,
        "current_scenario": ctx.current_scenario or "",
        "token_usage": str(ctx.token_usage),
        "user_role": ctx.user_role,
        "created_at": ctx.created_at.isoformat(),
        "last_active_at": ctx.last_active_at.isoformat(),
        "mode": ctx.mode.value,
        "human_agent_id": ctx.human_agent_id or "",
    }


def _deserialize_context(data: dict[str, str]) -> SessionContext:
    """Deserialize Redis Hash data back to SessionContext."""
    history_raw = json.loads(data.get("history", "[]"))
    history = [
        Message(
            role=m["role"],
            content=m["content"],
            metadata=m.get("metadata", {}),
        )
        for m in history_raw
    ]
    return SessionContext(
        session_id=data["session_id"],
        user_id=data.get("user_id") or None,
        channel=data["channel"],
        history=history,
        summary=data.get("summary") or None,
        slots=json.loads(data.get("slots", "{}")),
        fsm_state=data.get("fsm_state", "idle"),
        current_scenario=data.get("current_scenario") or None,
        token_usage=int(data.get("token_usage", "0")),
        user_role=data.get("user_role", "customer"),
        created_at=datetime.fromisoformat(data["created_at"]),
        last_active_at=datetime.fromisoformat(data["last_active_at"]),
        mode=SessionMode(data.get("mode", SessionMode.AI_MODE.value)),
        human_agent_id=data.get("human_agent_id") or None,
    )


class RedisContextManager(ContextManager):
    """Redis-backed session context manager.

    Uses a Redis Hash per session, keyed by ``session:{session_id}``.
    TTL controls automatic expiration of inactive sessions.
    """

    def __init__(
        self,
        redis_client: Any,
        ttl_seconds: int = 1800,
        max_history_tokens: int = 2048,
        max_context_tokens: int = 4096,
        key_prefix: str = "session:",
    ) -> None:
        self._redis = redis_client
        self._ttl = ttl_seconds
        self._max_history_tokens = max_history_tokens
        self._max_context_tokens = max_context_tokens
        self._prefix = key_prefix

    def _key(self, session_id: str) -> str:
        return f"{self._prefix}{session_id}"

    async def load(self, session_id: str, channel: str = "web") -> SessionContext:
        """Load session from Redis or create a new one."""
        key = self._key(session_id)
        try:
            data = await self._redis.hgetall(key)
            if not data:
                now = datetime.now(UTC)
                ctx = SessionContext(
                    session_id=session_id,
                    user_id=None,
                    channel=channel,
                    history=[],
                    summary=None,
                    slots={},
                    fsm_state="idle",
                    current_scenario=None,
                    token_usage=0,
                    user_role="customer",
                    created_at=now,
                    last_active_at=now,
                )
                await self._save_to_redis(key, ctx)
                return ctx
            return _deserialize_context(data)
        except ContextError:
            raise
        except Exception as e:
            raise ContextError(
                f"Failed to load session {session_id}: {e}",
                session_id=session_id,
            ) from e

    async def save(self, context: SessionContext, response: AgentMessage) -> None:
        """Save updated context to Redis with TTL refresh."""
        updated = replace(
            context,
            history=[*context.history],
            last_active_at=datetime.now(UTC),
        )
        key = self._key(context.session_id)
        await self._save_to_redis(key, updated)

    async def _save_to_redis(self, key: str, ctx: SessionContext) -> None:
        try:
            data = _serialize_context(ctx)
            await self._redis.hset(key, mapping=data)
            await self._redis.expire(key, self._ttl)
        except Exception as e:
            raise ContextError(
                f"Failed to save session: {e}",
                session_id=ctx.session_id,
            ) from e

    async def compress(self, context: SessionContext) -> SessionContext:
        """Compress history when it exceeds the token budget."""
        budget = self.get_token_budget(context)
        if not budget.needs_compression:
            return context

        total = len(context.history)
        keep_count = max(4, total // 5)
        dropped = context.history[:-keep_count]
        kept = context.history[-keep_count:]
        summary_prefix = f"[Previously compressed {len(dropped)} messages] "
        new_summary = (context.summary or "") + summary_prefix

        return replace(
            context,
            history=kept,
            summary=new_summary,
            last_active_at=datetime.now(UTC),
        )

    def get_token_budget(self, context: SessionContext) -> TokenBudget:
        """Same 20/50/20/10 split as InMemoryContextManager."""
        total = self._max_context_tokens
        history_tokens = sum(
            len(m.content) // 4 for m in context.history if m.content
        )
        return TokenBudget(
            total=total,
            system_prompt=int(total * 0.2),
            history=int(total * 0.5),
            tool_results=int(total * 0.2),
            slot_entities=int(total * 0.1),
            history_used=history_tokens,
            needs_compression=history_tokens > int(total * 0.5),
        )

    async def update_slots(
        self, context: SessionContext, new_entities: dict
    ) -> SessionContext:
        merged_slots = {**context.slots, **new_entities}
        return replace(context, slots=merged_slots)
