"""Integration: DialogueOrchestrator wired to the REAL DatabaseContextManager.

This seam was untested — the orchestrator and the DB backend were fixed by
independent agents with contradictory contracts (the orchestrator's _record_turn
appends the assistant reply to context.history; the DB save ALSO re-appended it),
and each side's unit tests passed in isolation. The result was every assistant
turn persisted TWICE on the DB backend. These tests lock the seam.
"""
from __future__ import annotations

import pytest

from open_chat_shop.core.context import InMemoryContextManager
from open_chat_shop.core.intent import CascadeIntentEngine, RuleBasedMatcher
from open_chat_shop.core.orchestrator import DialogueOrchestrator
from open_chat_shop.core.security import SecurityGuard
from open_chat_shop.core.strategy import RuleBasedStrategy
from open_chat_shop.core.tool import ToolInjector
from open_chat_shop.core.types import UserMessage
from open_chat_shop.storage.db_context import DatabaseContextManager


def _orchestrator(ctx_mgr: object) -> DialogueOrchestrator:
    return DialogueOrchestrator(
        security_guard=SecurityGuard({}),
        context_manager=ctx_mgr,
        intent_engine=CascadeIntentEngine(RuleBasedMatcher()),
        tool_injector=ToolInjector(registry={}, routing_rules=[]),
        strategy=RuleBasedStrategy(),
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_db_backend_persists_each_assistant_turn_once() -> None:
    """A multi-turn conversation on the DB backend must NOT duplicate replies."""
    mgr = DatabaseContextManager(db_url="sqlite:///:memory:")
    orch = _orchestrator(mgr)
    sid = "seam-1"

    for content in ("你好", "我想查订单"):
        await orch.handle_message(UserMessage(session_id=sid, content=content, channel="web"))

    reloaded = await mgr.load(sid)
    user_turns = [m for m in reloaded.history if m.role == "user"]
    asst_turns = [m for m in reloaded.history if m.role == "assistant"]
    # 2 turns => exactly 2 user + 2 assistant rows. The regression produced 4
    # assistant rows (each reply written twice).
    assert len(user_turns) == 2, [m.content for m in reloaded.history]
    assert len(asst_turns) == 2, [m.content for m in reloaded.history]
    assert len(reloaded.history) == 4


@pytest.mark.integration
@pytest.mark.asyncio
async def test_db_and_inmemory_history_agree() -> None:
    """The DB backend and InMemory backend must round-trip identical history."""
    sid = "seam-2"
    turns = ("你好", "帮我查一下")

    db = DatabaseContextManager(db_url="sqlite:///:memory:")
    od = _orchestrator(db)
    for c in turns:
        await od.handle_message(UserMessage(session_id=sid, content=c, channel="web"))
    db_hist = [(m.role, m.content) for m in (await db.load(sid)).history]

    mem = InMemoryContextManager()
    om = _orchestrator(mem)
    for c in turns:
        await om.handle_message(UserMessage(session_id=sid, content=c, channel="web"))
    mem_hist = [(m.role, m.content) for m in (await mem.load(sid)).history]

    assert db_hist == mem_hist, f"DB={db_hist} != InMemory={mem_hist}"
