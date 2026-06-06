"""Database-backed ContextManager using SQLModel.

Persists SessionContext to the database via ConversationLog entries.
Supports session recovery across restarts.

History is stored as a faithful mirror of ``context.history`` plus the latest
assistant ``response``: every ``save`` reconciles the persisted rows against the
(already compressed) in-memory history, so compaction actually shrinks what is
stored and the row count never grows without bound. The reconciliation diffs the
desired row sequence against what is already persisted and only rewrites the
divergent tail — unchanged prior rows keep their identity, so a steady
append-only conversation writes one user + one assistant row per turn instead of
deleting and re-inserting the whole history (O(N) write amplification per turn).
Cumulative token usage is kept authoritatively on the ``__session_meta__`` row so
it survives compaction and reload. The synchronous SQLModel work runs on a worker
thread via ``asyncio.to_thread`` so it never blocks the event loop.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast

from open_chat_shop.core.context import ContextManager
from open_chat_shop.core.exceptions import ContextError
from open_chat_shop.core.types import (
    AgentMessage,
    Message,
    SessionContext,
    SessionMode,
    TokenBudget,
)
from open_chat_shop.storage.database import create_tables, get_engine, get_session
from open_chat_shop.storage.models import ConversationLog


def _as_aware_utc(ts: datetime) -> datetime:
    """Return ``ts`` as a tz-aware UTC datetime (SQLite reloads are tz-naive)."""
    return ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts


def _is_memory_sqlite(db_url: str) -> bool:
    """True for in-memory SQLite URLs (``sqlite://`` or ``sqlite:///:memory:``)."""
    normalized = db_url.strip().lower()
    return normalized in ("sqlite://", "sqlite:///:memory:") or normalized.endswith(
        ":memory:"
    )


def _build_engine(db_url: str) -> Any:
    """Build the engine, sharing a single connection for in-memory SQLite.

    Once DB work is offloaded to a worker thread (see ``load``/``save``), an
    in-memory SQLite database — which is private per connection — would be
    invisible to the worker thread's connection. ``StaticPool`` +
    ``check_same_thread=False`` pins one shared connection so the schema and
    rows are visible across threads. File-backed SQLite and other databases
    share state across connections, so they use the default engine unchanged.
    """
    if _is_memory_sqlite(db_url):
        from sqlalchemy.pool import StaticPool
        from sqlmodel import create_engine

        return create_engine(
            db_url,
            echo=False,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    return get_engine(db_url)

logger = logging.getLogger(__name__)

# Safety cap on how many history rows ``load`` reconstructs per session. The
# in-memory contract keeps history small via compaction, so this only guards
# against pathological row growth; it is intentionally generous.
_HISTORY_ROW_LIMIT = 200

_META_ROLE = "__session_meta__"


class DatabaseContextManager(ContextManager):
    """SQLModel-backed session context manager.

    Stores session metadata in a special ConversationLog entry
    (role='__session_meta__') per session, including the authoritative
    cumulative token usage. History messages are stored as regular
    ConversationLog rows that mirror ``context.history`` plus the latest
    assistant response.
    """

    def __init__(
        self,
        db_url: str = "sqlite:///data/commerce.db",
        max_history_tokens: int = 2048,
        max_context_tokens: int = 4096,
    ) -> None:
        self._engine = _build_engine(db_url)
        create_tables(self._engine)
        self._max_history_tokens = max_history_tokens
        self._max_context_tokens = max_context_tokens
        # Write-through in-process cache so the sync ``get`` (used by API guards
        # that cannot await the DB) can return the last loaded/saved context
        # without blocking I/O. The database remains the source of truth.
        self._cache: dict[str, SessionContext] = {}

    async def load(self, session_id: str, channel: str = "web") -> SessionContext:
        """Load session from database or create a new one.

        The blocking SQLModel work runs on a worker thread so the event loop
        is not stalled while the query executes.
        """
        # Bound the write-through cache (a sync-get optimization; the DB is the
        # source of truth, so dropping it is safe) to avoid unbounded growth
        # across distinct sessions over a long-running process (audit MEDIUM).
        if len(self._cache) > 10_000:
            self._cache.clear()
        ctx = await asyncio.to_thread(self._load_sync, session_id, channel)
        self._cache[session_id] = ctx
        return ctx

    def _load_sync(self, session_id: str, channel: str) -> SessionContext:
        with get_session(self._engine) as session:
            from sqlmodel import col, select

            meta_entry = session.exec(
                select(ConversationLog).where(
                    ConversationLog.session_id == session_id,
                    ConversationLog.role == _META_ROLE,
                )
            ).first()

            if meta_entry:
                meta = json.loads(meta_entry.content)
                created_at = datetime.fromisoformat(meta["created_at"])
                last_active_at = datetime.fromisoformat(meta["last_active_at"])
            else:
                meta = {}
                created_at = datetime.now(UTC)
                last_active_at = created_at

            # Bound the reconstruction: take the most recent rows then restore
            # chronological order. Mirrors the in-memory (compacted) history.
            rows = session.exec(
                select(ConversationLog)
                .where(
                    ConversationLog.session_id == session_id,
                    ConversationLog.role != _META_ROLE,
                )
                .order_by(col(ConversationLog.created_at).desc())
                .limit(_HISTORY_ROW_LIMIT)
            ).all()
            logs = list(reversed(rows))

            history = [
                Message(
                    role=cast(
                        Literal["system", "user", "assistant", "tool"], log.role
                    ),
                    content=log.content,
                    timestamp=log.created_at,
                )
                for log in logs
            ]

        # Authoritative cumulative usage lives on the meta row; it survives
        # compaction (which prunes old history rows) and reload.
        token_usage = int(meta.get("token_usage", 0))

        return SessionContext(
            session_id=session_id,
            user_id=meta.get("user_id"),
            channel=meta.get("channel", channel),
            history=history,
            summary=meta.get("summary"),
            slots=meta.get("slots", {}),
            fsm_state=meta.get("fsm_state", "idle"),
            current_scenario=meta.get("current_scenario"),
            token_usage=token_usage,
            user_role=meta.get("user_role", "customer"),
            created_at=created_at,
            last_active_at=last_active_at,
            mode=SessionMode(meta.get("mode", SessionMode.AI_MODE.value)),
            human_agent_id=meta.get("human_agent_id"),
        )

    async def save(self, context: SessionContext, response: AgentMessage) -> None:
        """Persist context: upsert metadata and mirror history + assistant turn.

        The blocking SQLModel work runs on a worker thread. The persisted
        history rows are reconciled to exactly ``context.history`` plus the new
        assistant ``response`` (old rows are pruned), so compaction shrinks
        storage instead of letting it grow unbounded. The real token count from
        ``response.meta['token_usage']`` is recorded on the assistant row and
        folded into the authoritative cumulative usage on the meta row.
        """
        response_tokens = int(response.meta.get("token_usage", 0) or 0)
        cumulative_tokens = context.token_usage + response_tokens
        now = datetime.now(UTC)
        # The assistant reply is the newest turn and must sort last on load.
        # Anchor it strictly after every history timestamp (and ``now``) so the
        # created_at ordering is deterministic even when history carries
        # synthetic or clock-skewed timestamps. History reloaded from SQLite is
        # tz-naive, so normalize before comparing to the tz-aware ``now``.
        reply_ts = now
        for msg in context.history:
            ts = _as_aware_utc(msg.timestamp)
            if ts >= reply_ts:
                reply_ts = ts + timedelta(microseconds=1)
        await asyncio.to_thread(
            self._save_sync,
            context,
            response,
            response_tokens,
            cumulative_tokens,
            now,
            reply_ts,
        )
        # Reflect what was persisted (incl. the new assistant turn and updated
        # cumulative usage) in the write-through cache used by ``get``.
        persisted_history = [
            *context.history,
            Message(
                role="assistant", content=response.text_fallback, timestamp=reply_ts
            ),
        ]
        self._cache[context.session_id] = replace(
            context,
            history=persisted_history,
            token_usage=cumulative_tokens,
            last_active_at=now,
        )

    def _save_sync(
        self,
        context: SessionContext,
        response: AgentMessage,
        response_tokens: int,
        cumulative_tokens: int,
        now: datetime,
        reply_ts: datetime,
    ) -> None:
        try:
            with get_session(self._engine) as db:
                from sqlmodel import col, select

                # Upsert session metadata (carries authoritative token usage).
                existing_meta = db.exec(
                    select(ConversationLog).where(
                        ConversationLog.session_id == context.session_id,
                        ConversationLog.role == _META_ROLE,
                    )
                ).first()

                created_at_iso = (
                    json.loads(existing_meta.content).get(
                        "created_at", context.created_at.isoformat()
                    )
                    if existing_meta
                    else context.created_at.isoformat()
                )
                meta_json = json.dumps(
                    {
                        "user_id": context.user_id,
                        "channel": context.channel,
                        "summary": context.summary,
                        "slots": context.slots,
                        "fsm_state": context.fsm_state,
                        "current_scenario": context.current_scenario,
                        "user_role": context.user_role,
                        "token_usage": cumulative_tokens,
                        "created_at": created_at_iso,
                        "last_active_at": now.isoformat(),
                        "mode": context.mode.value,
                        "human_agent_id": context.human_agent_id,
                    },
                    ensure_ascii=False,
                )

                if existing_meta:
                    existing_meta.content = meta_json
                    db.add(existing_meta)
                else:
                    db.add(
                        ConversationLog(
                            session_id=context.session_id,
                            user_id=context.user_id,
                            role=_META_ROLE,
                            content=meta_json,
                        )
                    )

                # Reconcile history rows to mirror the (compacted) in-memory
                # history followed by the new assistant turn, but WITHOUT the
                # delete-all + reinsert-all that caused O(N) write amplification
                # every turn (audit OPT). We diff the desired row sequence
                # against what is already persisted (ordered by created_at, the
                # same order ``load`` reconstructs) and only touch the divergent
                # tail: unchanged prior rows keep their identity and are never
                # rewritten, so a steady append-only conversation writes ONE new
                # user row + one assistant row per turn instead of 2N.

                # Desired sequence = context.history, plus the assistant reply
                # ONLY if context.history does not already end with it. The
                # orchestrator's _record_turn appends the reply to
                # context.history BEFORE calling save (so it is already part of
                # ``history``); direct callers may pass history without it.
                # Without this guard the DB backend stored the reply twice every
                # turn — a regression where _record_turn and this append both ran
                # across an untested seam, so the de-dup MUST be preserved.
                last = context.history[-1] if context.history else None
                already_appended = (
                    last is not None
                    and last.role == "assistant"
                    and last.content == response.text_fallback
                )
                desired: list[tuple[str, str, datetime, int]] = [
                    (msg.role, msg.content, msg.timestamp, 0)
                    for msg in context.history
                ]
                if not already_appended:
                    desired.append(
                        ("assistant", response.text_fallback, reply_ts, response_tokens)
                    )

                # Existing non-meta rows in the SAME chronological order load
                # uses (ascending created_at). No row limit here: reconciliation
                # must see every stale row so compaction can delete them.
                existing_rows = db.exec(
                    select(ConversationLog)
                    .where(
                        ConversationLog.session_id == context.session_id,
                        ConversationLog.role != _META_ROLE,
                    )
                    .order_by(col(ConversationLog.created_at).asc())
                ).all()

                # Longest common prefix of (role, content, normalized timestamp).
                # SQLite reloads timestamps tz-naive, so normalize both sides to
                # tz-aware UTC before comparing (a stable in-memory row matches
                # its persisted copy exactly — see microsecond round-trip test).
                prefix = 0
                limit = min(len(existing_rows), len(desired))
                while prefix < limit:
                    row = existing_rows[prefix]
                    role, content, ts, _tokens = desired[prefix]
                    if (
                        row.role == role
                        and row.content == content
                        and _as_aware_utc(row.created_at) == _as_aware_utc(ts)
                    ):
                        prefix += 1
                    else:
                        break

                # Delete only the divergent / surplus tail of persisted rows
                # (everything compaction dropped or that changed); keep the
                # matched prefix untouched so prior rows are never rewritten.
                for row in existing_rows[prefix:]:
                    db.delete(row)

                # Insert only the new / changed tail of the desired sequence.
                for role, content, ts, tokens in desired[prefix:]:
                    db.add(
                        ConversationLog(
                            session_id=context.session_id,
                            user_id=context.user_id,
                            role=role,
                            content=content,
                            intent_name=None,
                            tokens_used=tokens,
                            created_at=ts,
                        )
                    )
        except Exception as e:
            raise ContextError(
                f"Failed to save context: {e}",
                session_id=context.session_id,
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
        """Same 20/50/20/10 split."""
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
        self, context: SessionContext, new_entities: dict[str, Any]
    ) -> SessionContext:
        merged_slots = {**context.slots, **new_entities}
        return replace(context, slots=merged_slots)

    def get(self, session_id: str) -> SessionContext | None:
        """Synchronous lookup from the write-through cache (no DB I/O).

        Returns the last context that ``load``/``save`` observed in this
        process, or ``None`` if the session has not been touched here.
        """
        return self._cache.get(session_id)
