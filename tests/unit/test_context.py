"""Unit tests for ContextManager (feat-004).

Tests cover:
- load: new session creation and existing session retrieval
- save: last_active_at update
- compress: triggers on budget excess, keeps recent messages,
            generates summary prefix, no-op when under budget
- get_token_budget: 20/50/20/10 split and compression detection
- update_slots: merges entities, preserves existing, immutability
"""

from __future__ import annotations

from datetime import datetime
import time

import pytest

from commerce_agent.core.context import InMemoryContextManager
from commerce_agent.core.types import AgentMessage, Message, SessionContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_message(content: str, role: str = "user") -> Message:
    """Create a Message with the given content."""
    return Message(role=role, content=content)


def _make_agent_message(text: str = "ok") -> AgentMessage:
    """Create a minimal AgentMessage."""
    return AgentMessage(
        message_type="text",
        payload={},
        text_fallback=text,
    )


def _make_context_with_history(
    session_id: str = "sess-1",
    message_count: int = 0,
    msg_chars: int = 100,
    slots: dict | None = None,
) -> SessionContext:
    """Create a SessionContext with the given number of history messages."""
    now = datetime.utcnow()
    messages = [
        _make_message("x" * msg_chars, role="user" if i % 2 == 0 else "assistant")
        for i in range(message_count)
    ]
    return SessionContext(
        session_id=session_id,
        user_id=None,
        channel="web",
        history=messages,
        summary=None,
        slots=slots or {},
        fsm_state="idle",
        current_scenario=None,
        token_usage=0,
        user_role="customer",
        created_at=now,
        last_active_at=now,
    )


# ---------------------------------------------------------------------------
# load tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_load_creates_new_session_for_unknown_id():
    """Loading an unknown session_id creates a fresh SessionContext."""
    mgr = InMemoryContextManager()
    ctx = await mgr.load("new-session")

    assert ctx.session_id == "new-session"
    assert ctx.user_id is None
    assert ctx.channel == "web"
    assert ctx.history == []
    assert ctx.summary is None
    assert ctx.slots == {}
    assert ctx.fsm_state == "idle"
    assert ctx.current_scenario is None
    assert ctx.token_usage == 0
    assert ctx.user_role == "customer"


@pytest.mark.unit
async def test_load_returns_existing_session():
    """Repeated loads for the same session_id return the same context."""
    mgr = InMemoryContextManager()
    ctx1 = await mgr.load("sess-1")

    # Modify and save
    updated = _make_context_with_history("sess-1", message_count=3)
    await mgr.save(updated, _make_agent_message())

    ctx2 = await mgr.load("sess-1")
    assert len(ctx2.history) == 3


# ---------------------------------------------------------------------------
# save tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_save_updates_last_active_at():
    """Saving a context updates the last_active_at timestamp."""
    mgr = InMemoryContextManager()
    ctx = await mgr.load("sess-1")
    original_active = ctx.last_active_at

    time.sleep(0.01)

    await mgr.save(ctx, _make_agent_message())
    saved = await mgr.load("sess-1")
    assert saved.last_active_at >= original_active


# ---------------------------------------------------------------------------
# compress tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_compress_triggers_when_history_exceeds_budget():
    """Compression activates when history token usage exceeds the 50% budget."""
    # max_context_tokens=4096 -> history budget = 2048 tokens
    # With 4 chars/token, we need > 2048*4 = 8192 chars total
    # 100 messages * 100 chars each = 10000 chars -> 2500 tokens > 2048
    mgr = InMemoryContextManager(max_context_tokens=4096)
    ctx = _make_context_with_history(message_count=100, msg_chars=100)

    budget = mgr.get_token_budget(ctx)
    assert budget.needs_compression, "History should exceed budget threshold"

    compressed = await mgr.compress(ctx)
    assert len(compressed.history) < len(ctx.history)


@pytest.mark.unit
async def test_compress_keeps_recent_messages():
    """After compression, the most recent messages are retained."""
    mgr = InMemoryContextManager(max_context_tokens=4096)
    ctx = _make_context_with_history(message_count=100, msg_chars=100)

    compressed = await mgr.compress(ctx)
    # keep_count = max(4, 100//5) = 20
    assert len(compressed.history) == 20
    # The last message content should be preserved
    assert compressed.history[-1].content == ctx.history[-1].content


@pytest.mark.unit
async def test_compress_generates_summary_prefix():
    """Compression appends a summary prefix indicating how many messages were dropped."""
    mgr = InMemoryContextManager(max_context_tokens=4096)
    ctx = _make_context_with_history(message_count=100, msg_chars=100)

    compressed = await mgr.compress(ctx)
    assert compressed.summary is not None
    assert "80" in compressed.summary  # 100 - 20 kept = 80 dropped


@pytest.mark.unit
async def test_compress_noop_when_under_budget():
    """Compression returns the same context unchanged when under budget."""
    mgr = InMemoryContextManager(max_context_tokens=4096)
    ctx = _make_context_with_history(message_count=3, msg_chars=50)

    budget = mgr.get_token_budget(ctx)
    assert not budget.needs_compression

    compressed = await mgr.compress(ctx)
    assert compressed is ctx  # identity check: same object returned


# ---------------------------------------------------------------------------
# get_token_budget tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_token_budget_calculates_split():
    """Token budget follows the 20/50/20/10 allocation split."""
    mgr = InMemoryContextManager(max_context_tokens=4096)
    ctx = _make_context_with_history(message_count=0)

    budget = mgr.get_token_budget(ctx)

    assert budget.total == 4096
    assert budget.system_prompt == int(4096 * 0.2)   # 819
    assert budget.history == int(4096 * 0.5)          # 2048
    assert budget.tool_results == int(4096 * 0.2)     # 819
    assert budget.slot_entities == int(4096 * 0.1)    # 409


@pytest.mark.unit
def test_token_budget_detects_compression_need():
    """needs_compression is True when history_used exceeds the history budget."""
    mgr = InMemoryContextManager(max_context_tokens=4096)
    # 100 msgs * 100 chars = 10000 chars / 4 = 2500 tokens > 2048 budget
    ctx = _make_context_with_history(message_count=100, msg_chars=100)

    budget = mgr.get_token_budget(ctx)
    assert budget.history_used > budget.history
    assert budget.needs_compression is True


# ---------------------------------------------------------------------------
# update_slots tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_update_slots_merges_new_entities():
    """New entities are merged into existing slots."""
    mgr = InMemoryContextManager()
    ctx = _make_context_with_history(slots={"order_id": "ORD-001"})

    updated = await mgr.update_slots(ctx, {"product_name": "Widget"})
    assert updated.slots == {"order_id": "ORD-001", "product_name": "Widget"}


@pytest.mark.unit
async def test_update_slots_preserves_existing_slots():
    """Slots not in new_entities remain unchanged."""
    mgr = InMemoryContextManager()
    ctx = _make_context_with_history(slots={"a": 1, "b": 2})

    updated = await mgr.update_slots(ctx, {"c": 3})
    assert "a" in updated.slots
    assert "b" in updated.slots
    assert updated.slots["a"] == 1
    assert updated.slots["b"] == 2


@pytest.mark.unit
async def test_update_slots_does_not_mutate_original():
    """update_slots returns a new context; the original is not mutated."""
    mgr = InMemoryContextManager()
    original = _make_context_with_history(slots={"x": 1})
    original_slots_id = id(original.slots)

    updated = await mgr.update_slots(original, {"y": 2})

    # The returned context is a different object
    assert updated is not original
    # The original slots dict is not mutated
    assert original.slots == {"x": 1}
    assert id(original.slots) == original_slots_id
    # The new context has merged slots
    assert updated.slots == {"x": 1, "y": 2}
