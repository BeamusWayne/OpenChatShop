"""Tests for DatabaseContextManager with SQLite in-memory."""
from __future__ import annotations

import pytest

from open_chat_shop.core.types import AgentMessage, Message, SessionContext, SessionMode
from open_chat_shop.storage.db_context import DatabaseContextManager


class TestDatabaseContextManager:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_load_creates_new_session(self):
        mgr = DatabaseContextManager(db_url="sqlite:///:memory:")
        ctx = await mgr.load("s1")
        assert ctx.session_id == "s1"
        assert ctx.history == []
        assert ctx.fsm_state == "idle"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_save_and_load(self):
        mgr = DatabaseContextManager(db_url="sqlite:///:memory:")
        ctx = await mgr.load("s1")
        response = AgentMessage(
            message_type="text",
            payload={"content": "hello"},
            text_fallback="hello",
        )
        await mgr.save(ctx, response)
        # Updated from the MVP behavior: save now actually round-trips the
        # assistant turn (audit STORAGE HIGH). The reload must contain the
        # persisted assistant message, not an empty history.
        ctx2 = await mgr.load("s1")
        assert ctx2.session_id == "s1"
        assert [m.content for m in ctx2.history] == ["hello"]
        assert ctx2.history[0].role == "assistant"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_compress_reduces_history(self):
        mgr = DatabaseContextManager(db_url="sqlite:///:memory:", max_context_tokens=100)
        from datetime import datetime
        history = [
            Message(role="user", content=f"message {i} " * 20)
            for i in range(10)
        ]
        ctx = SessionContext(
            session_id="s1", user_id="u1", channel="web",
            history=history, created_at=datetime.utcnow(),
            last_active_at=datetime.utcnow(),
        )
        compressed = await mgr.compress(ctx)
        assert len(compressed.history) < len(history)
        assert "compressed" in (compressed.summary or "")

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_compress_no_op_when_under_budget(self):
        mgr = DatabaseContextManager(db_url="sqlite:///:memory:", max_context_tokens=100_000)
        from datetime import datetime
        ctx = SessionContext(
            session_id="s1", user_id="u1", channel="web",
            history=[Message(role="user", content="short")],
            created_at=datetime.utcnow(), last_active_at=datetime.utcnow(),
        )
        compressed = await mgr.compress(ctx)
        assert len(compressed.history) == 1

    @pytest.mark.unit
    def test_get_token_budget(self):
        mgr = DatabaseContextManager(db_url="sqlite:///:memory:", max_context_tokens=4096)
        from datetime import datetime
        ctx = SessionContext(
            session_id="s1", user_id="u1", channel="web",
            history=[], created_at=datetime.utcnow(),
            last_active_at=datetime.utcnow(),
        )
        budget = mgr.get_token_budget(ctx)
        assert budget.total == 4096
        assert budget.system_prompt == 819
        assert budget.history == 2048

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_update_slots(self):
        mgr = DatabaseContextManager(db_url="sqlite:///:memory:")
        from datetime import datetime
        ctx = SessionContext(
            session_id="s1", user_id="u1", channel="web",
            slots={"a": "1"}, created_at=datetime.utcnow(),
            last_active_at=datetime.utcnow(),
        )
        updated = await mgr.update_slots(ctx, {"b": "2"})
        assert updated.slots == {"a": "1", "b": "2"}
        assert ctx.slots == {"a": "1"}

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_save_load_preserves_mode_and_human_agent_id(self):
        """Regression: mode=HUMAN_MODE and human_agent_id survive a full save→load cycle."""
        mgr = DatabaseContextManager(db_url="sqlite:///:memory:")
        from datetime import datetime

        ctx = SessionContext(
            session_id="s-human",
            user_id="u1",
            channel="web",
            history=[],
            created_at=datetime.utcnow(),
            last_active_at=datetime.utcnow(),
            mode=SessionMode.HUMAN_MODE,
            human_agent_id="agent-7",
        )
        response = AgentMessage(
            message_type="text",
            payload={"content": "ok"},
            text_fallback="ok",
        )
        await mgr.save(ctx, response)

        loaded = await mgr.load("s-human")
        assert loaded.mode == SessionMode.HUMAN_MODE
        assert loaded.human_agent_id == "agent-7"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_multiple_sessions_independent(self):
        mgr = DatabaseContextManager(db_url="sqlite:///:memory:")
        ctx1 = await mgr.load("s1")
        ctx2 = await mgr.load("s2")
        assert ctx1.session_id == "s1"
        assert ctx2.session_id == "s2"
        assert ctx1 is not ctx2
