"""Re-audit LOW-1: internal/underscore slots must not fragment the response cache.

``_enrich_with_context`` merges ``context.slots`` into ``intent.entities``,
including internal control dicts (``_pending_action`` / ``_pending_confirmation``
/ ``_clarifying_response``) and stale slots. The orchestrator builds the
response-cache key from ``intent.entities``, so before the fix those churning
underscore keys produced a different key every turn — logically-identical
read-only queries missed the cache (near-zero hit rate). The fix drops
underscore-prefixed keys from the cache params and builds them once for both the
``get`` and the ``set``.
"""
from __future__ import annotations

from typing import Any

import pytest

from open_chat_shop.core.cache import ResponseCache
from open_chat_shop.core.context import InMemoryContextManager
from open_chat_shop.core.orchestrator import DialogueOrchestrator
from open_chat_shop.core.security import SecurityGuard
from open_chat_shop.core.tool import ToolInjector
from open_chat_shop.core.types import Action, Intent, SessionContext, UserMessage


class _StubIntentEngine:
    """Returns a fixed cacheable intent whose entities we control per turn."""

    def __init__(self) -> None:
        self._entities: dict[str, Any] = {}

    def set_entities(self, entities: dict[str, Any]) -> None:
        self._entities = entities

    async def classify(self, message: UserMessage, context: SessionContext) -> Intent:
        return Intent(
            name="search_product",
            display_name="搜索商品",
            confidence=1.0,
            source="rule",
            entities=dict(self._entities),
        )


class _CountingStrategy:
    """Counts decisions so a cache hit (no re-decide) is observable."""

    def __init__(self) -> None:
        self.calls = 0

    async def decide(
        self, intent: Intent, context: SessionContext, tools: list[Any]
    ) -> Action:
        self.calls += 1
        return Action(
            type="reply",
            payload={"message_type": "text", "content": f"result-{self.calls}"},
        )


def _build() -> tuple[DialogueOrchestrator, _StubIntentEngine, _CountingStrategy]:
    engine = _StubIntentEngine()
    strategy = _CountingStrategy()
    orch = DialogueOrchestrator(
        security_guard=SecurityGuard({}),
        context_manager=InMemoryContextManager(),
        intent_engine=engine,
        tool_injector=ToolInjector(registry={}, routing_rules=[]),
        strategy=strategy,
    )
    orch.set_response_cache(ResponseCache())
    return orch, engine, strategy


def _msg(content: str) -> UserMessage:
    return UserMessage(session_id="s1", content=content, channel="web")


class TestInternalSlotsDoNotFragmentCache:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_churning_underscore_slots_still_hit_cache(self) -> None:
        orch, engine, strategy = _build()

        # Turn 1 populates the cache. entities carry an internal _pending_action
        # (as _enrich_with_context would merge from slots).
        engine.set_entities({"keyword": "shoes", "_pending_action": {"step": 1}})
        first = await orch.handle_message(_msg("有运动鞋吗"))
        assert strategy.calls == 1
        assert first.text_fallback == "result-1"

        # Turn 2: identical user query, but the internal control state churned.
        # The cache key must ignore underscore keys, so this is a HIT and the
        # strategy is NOT re-run (pre-fix: different key -> miss -> calls == 2).
        engine.set_entities({"keyword": "shoes", "_pending_action": {"step": 2}})
        second = await orch.handle_message(_msg("有运动鞋吗"))
        assert strategy.calls == 1, "internal slots fragmented the cache key"
        assert second.text_fallback == "result-1"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_real_entity_change_still_misses(self) -> None:
        """A change to a REQUEST-relevant (non-underscore) entity must still
        produce a distinct key — the fix only ignores internal keys, it must not
        collapse genuinely different queries into one entry."""
        orch, engine, strategy = _build()

        engine.set_entities({"keyword": "shoes"})
        await orch.handle_message(_msg("有运动鞋吗"))
        assert strategy.calls == 1

        # Different keyword -> different logical query -> must re-decide.
        engine.set_entities({"keyword": "hats"})
        await orch.handle_message(_msg("有运动鞋吗"))
        assert strategy.calls == 2
