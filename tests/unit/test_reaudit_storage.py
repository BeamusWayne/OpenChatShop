"""Re-audit regression tests for the STORAGE cluster (write amplification).

Finding (OPT): ``DatabaseContextManager._save_sync`` used to delete EVERY
non-meta ``ConversationLog`` row and re-insert all of ``context.history`` on
every ``save`` — O(N) write amplification that grows with session length. The
fix diffs the desired row sequence against what is already persisted and only
rewrites the divergent tail, so unchanged prior rows keep their identity.

These tests pin the optimized behavior and FAIL against the old delete+reinsert
implementation:

* ``test_prior_rows_keep_identity_across_appends`` — the primary-key ``id`` of
  rows written in earlier turns is unchanged after later saves. Under the old
  full delete+reinsert every row was destroyed and recreated with a fresh UUID,
  so this assertion fails pre-fix.
* ``test_append_turn_writes_only_the_new_tail`` — spying on ``Session.add`` /
  ``Session.delete`` shows an append-only turn inserts only the new rows and
  deletes nothing, instead of deleting N and inserting N.

It also re-locks the correctness contracts the optimization must not break
(compaction shrinks storage; identical re-saves never grow row count), distinct
from ``test_audit_storage.py`` which asserts them at the load() level.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import col, select

from open_chat_shop.core.types import AgentMessage, Message, SessionContext
from open_chat_shop.storage.database import get_session
from open_chat_shop.storage.db_context import DatabaseContextManager
from open_chat_shop.storage.models import ConversationLog


def _reply(text: str = "ok", *, tokens: int | None = None) -> AgentMessage:
    meta = {"token_usage": tokens} if tokens is not None else {}
    return AgentMessage(
        message_type="text",
        payload={"content": text},
        text_fallback=text,
        meta=meta,
    )


def _ctx(session_id: str = "s1", **overrides: object) -> SessionContext:
    now = datetime.now(UTC)
    defaults: dict[str, object] = dict(
        session_id=session_id,
        user_id="u1",
        channel="web",
        history=[],
        created_at=now,
        last_active_at=now,
    )
    defaults.update(overrides)
    return SessionContext(**defaults)  # type: ignore[arg-type]


def _history_rows(
    mgr: DatabaseContextManager, session_id: str
) -> list[tuple[str, str, str]]:
    """(primary-key id, role, content) for each non-meta row, oldest first.

    Tuples are materialized INSIDE the session scope so callers can inspect
    them after the session closes (ORM instances would raise
    DetachedInstanceError on lazy attribute access). The ``id`` is a fresh UUID
    per inserted row, so a changed id reveals a delete+reinsert rewrite.
    """
    with get_session(mgr._engine) as db:
        rows = db.exec(
            select(ConversationLog)
            .where(
                ConversationLog.session_id == session_id,
                ConversationLog.role != "__session_meta__",
            )
            .order_by(col(ConversationLog.created_at).asc())
        ).all()
        return [(r.id, r.role, r.content) for r in rows]


# ===========================================================================
# OPT — prior rows are not rewritten; only the divergent tail is written
# ===========================================================================


class TestNoWriteAmplification:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_prior_rows_keep_identity_across_appends(self) -> None:
        """A 3-turn append-only session must NOT rewrite earlier turns' rows.

        Each ConversationLog row gets a fresh UUID primary key on construction.
        The old _save_sync deleted all rows and re-inserted the whole history
        every turn, so every row's id changed each save. The diff-based fix
        keeps unchanged prior rows untouched, so their ids are stable.
        """
        mgr = DatabaseContextManager(db_url="sqlite:///:memory:")
        sid = "append-3"
        base = datetime.now(UTC)

        # Build history incrementally the way the orchestrator does: each save
        # carries the FULL prior history plus the freshly-appended turn. The
        # earlier rows keep stable timestamps (they are reused Message objects),
        # which is exactly what lets the reconciler match them.
        turn1 = [
            Message(role="user", content="你好", timestamp=base),
            Message(role="assistant", content="您好，有什么可以帮您",
                    timestamp=base + timedelta(seconds=1)),
        ]
        await mgr.save(_ctx(sid, history=list(turn1)), _reply("您好，有什么可以帮您"))
        id_after_t1 = _history_rows(mgr, sid)
        assert [c for _, _, c in id_after_t1] == ["你好", "您好，有什么可以帮您"]

        # Turn 2: append a new user + assistant turn (new timestamps), prior
        # turn unchanged.
        turn2 = [
            *turn1,
            Message(role="user", content="我想查订单",
                    timestamp=base + timedelta(seconds=2)),
            Message(role="assistant", content="请提供订单号",
                    timestamp=base + timedelta(seconds=3)),
        ]
        await mgr.save(_ctx(sid, history=list(turn2)), _reply("请提供订单号"))
        id_after_t2 = _history_rows(mgr, sid)

        # The first two rows must be byte-for-byte the SAME rows (same id) as
        # after turn 1 — proof they were not deleted+reinserted.
        assert id_after_t2[:2] == id_after_t1, (
            "prior turn rows were rewritten on append (write amplification): "
            f"{id_after_t1} -> {id_after_t2[:2]}"
        )
        assert [c for _, _, c in id_after_t2] == [
            "你好", "您好，有什么可以帮您", "我想查订单", "请提供订单号",
        ]

        # Turn 3: append once more; the first FOUR rows keep their identity.
        turn3 = [
            *turn2,
            Message(role="user", content="订单 A1",
                    timestamp=base + timedelta(seconds=4)),
            Message(role="assistant", content="已找到",
                    timestamp=base + timedelta(seconds=5)),
        ]
        await mgr.save(_ctx(sid, history=list(turn3)), _reply("已找到"))
        id_after_t3 = _history_rows(mgr, sid)

        assert id_after_t3[:4] == id_after_t2, (
            "earlier rows were rewritten on the 3rd turn (O(N) write "
            f"amplification persists): {id_after_t2} -> {id_after_t3[:4]}"
        )
        assert len(id_after_t3) == 6

        # And it still round-trips correctly through load().
        loaded = await mgr.load(sid)
        assert [m.content for m in loaded.history] == [
            "你好", "您好，有什么可以帮您", "我想查订单",
            "请提供订单号", "订单 A1", "已找到",
        ]

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_append_turn_writes_only_the_new_tail(self, monkeypatch) -> None:
        """An append-only save inserts only the new rows and deletes nothing.

        We spy on the SQLModel Session's add/delete. The old implementation
        deleted N rows and inserted N (full rewrite); the fix deletes 0 and
        inserts only the 2 appended rows (meta upsert is an add on the existing
        instance, which we exclude by role).
        """
        mgr = DatabaseContextManager(db_url="sqlite:///:memory:")
        sid = "spy-append"
        base = datetime.now(UTC)

        seed = [
            Message(role="user", content="a", timestamp=base),
            Message(role="assistant", content="b", timestamp=base + timedelta(seconds=1)),
            Message(role="user", content="c", timestamp=base + timedelta(seconds=2)),
            Message(role="assistant", content="d", timestamp=base + timedelta(seconds=3)),
        ]
        await mgr.save(_ctx(sid, history=list(seed)), _reply("d"))

        from sqlalchemy.orm import Session as SASession

        # Capture (role, content) AT spy time — the instances are detached once
        # the session closes, so we cannot read their attributes afterwards.
        added: list[tuple[str, str]] = []
        deleted: list[tuple[str, str]] = []
        real_add = SASession.add
        real_delete = SASession.delete

        def spy_add(self, instance, *a, **k):  # type: ignore[no-untyped-def]
            if isinstance(instance, ConversationLog):
                added.append((instance.role, instance.content))
            return real_add(self, instance, *a, **k)

        def spy_delete(self, instance, *a, **k):  # type: ignore[no-untyped-def]
            if isinstance(instance, ConversationLog):
                deleted.append((instance.role, instance.content))
            return real_delete(self, instance, *a, **k)

        monkeypatch.setattr(SASession, "add", spy_add)
        monkeypatch.setattr(SASession, "delete", spy_delete)

        # Append one new turn on top of the 4 seeded rows.
        appended = [
            *seed,
            Message(role="user", content="e", timestamp=base + timedelta(seconds=4)),
            Message(role="assistant", content="f", timestamp=base + timedelta(seconds=5)),
        ]
        await mgr.save(_ctx(sid, history=list(appended)), _reply("f"))

        # NO history rows deleted (the prior 4 are untouched). The meta row is
        # upserted via db.add on the existing instance, never deleted.
        history_deletes = [rc for rc in deleted if rc[0] != "__session_meta__"]
        assert history_deletes == [], (
            f"append turn deleted prior history rows: {history_deletes}"
        )
        # Only the 2 new history rows are inserted; the meta upsert re-adds the
        # existing meta instance, which we exclude by role.
        history_inserts = [rc for rc in added if rc[0] != "__session_meta__"]
        assert history_inserts == [
            ("user", "e"),
            ("assistant", "f"),
        ], "append turn rewrote more than the new tail"


# ===========================================================================
# Correctness the optimization must NOT break (re-locked at the row level)
# ===========================================================================


class TestOptimizationStaysCorrect:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_compaction_still_shrinks_persisted_rows(self) -> None:
        """When history shrinks (compaction), surplus rows are deleted.

        The diff must not become append-only: a shorter desired sequence has to
        delete the trailing persisted rows so storage actually shrinks.
        """
        mgr = DatabaseContextManager(db_url="sqlite:///:memory:")
        sid = "compact"
        base = datetime.now(UTC)
        long_history = [
            Message(
                role="user" if i % 2 == 0 else "assistant",
                content=f"turn {i}",
                timestamp=base + timedelta(seconds=i),
            )
            for i in range(20)
        ]
        await mgr.save(_ctx(sid, history=list(long_history)), _reply("latest"))
        assert len(_history_rows(mgr, sid)) == 21  # 20 + assistant reply

        # Persist a compacted context keeping only the last 4 turns.
        await mgr.save(_ctx(sid, history=long_history[-4:]), _reply("after-compaction"))

        rows = _history_rows(mgr, sid)
        assert len(rows) == 5, (
            f"compaction left {len(rows)} rows (storage did not shrink)"
        )
        assert rows[-1][2] == "after-compaction"  # (id, role, content)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_identical_resave_does_not_grow_or_rewrite_history(self) -> None:
        """Re-saving the SAME context keeps the user row's identity stable.

        The orchestrator path leaves the assistant reply already in history
        (already_appended), so the desired sequence == context.history. A second
        identical save must change nothing for the existing rows — same ids,
        same count. The reply de-dup guard ('already_appended') is what keeps the
        assistant turn from being duplicated.
        """
        mgr = DatabaseContextManager(db_url="sqlite:///:memory:")
        sid = "resave"
        base = datetime.now(UTC)
        # Reply is already the last history entry => already_appended path.
        ctx = _ctx(
            sid,
            history=[
                Message(role="user", content="hi", timestamp=base),
                Message(role="assistant", content="hello",
                        timestamp=base + timedelta(seconds=1)),
            ],
        )
        await mgr.save(ctx, _reply("hello"))
        first = _history_rows(mgr, sid)
        assert [c for _, _, c in first] == ["hi", "hello"]

        # Save the very same context again — nothing should be rewritten.
        await mgr.save(ctx, _reply("hello"))
        second = _history_rows(mgr, sid)

        assert second == first, (
            "identical re-save rewrote or duplicated history rows: "
            f"{first} -> {second}"
        )

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_token_usage_still_recovers_after_optimization(self) -> None:
        """Cumulative token usage (meta row) still accumulates across saves."""
        mgr = DatabaseContextManager(db_url="sqlite:///:memory:")
        sid = "tok"
        await mgr.save(_ctx(sid), _reply("a", tokens=100))
        ctx2 = await mgr.load(sid)
        assert ctx2.token_usage == 100

        await mgr.save(ctx2, _reply("b", tokens=50))
        ctx3 = await mgr.load(sid)
        assert ctx3.token_usage == 150
