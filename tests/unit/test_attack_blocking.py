"""Regression: every 'attack' golden sample must be neutralized (no tool runs).

The golden samples previously encoded the OPPOSITE expectation — they asserted
the injection "忽略之前的指令…" should be understood as query_order and EXECUTE
the tool. The system actually blocks/neutralizes all of them (3 via the prompt-
injection detector, 5 via intent fallback). This test locks that security
property — and the corrected dataset — against regression.
"""
from __future__ import annotations

import json
from pathlib import Path

from open_chat_shop import evaluation
from open_chat_shop.core.context import InMemoryContextManager
from open_chat_shop.core.intent import CascadeIntentEngine, RuleBasedMatcher
from open_chat_shop.core.orchestrator import DialogueOrchestrator
from open_chat_shop.core.security import SecurityGuard
from open_chat_shop.core.strategy import RuleBasedStrategy
from open_chat_shop.core.tool import ToolInjector
from open_chat_shop.core.types import RoutingRule, UserMessage
from open_chat_shop.tools.builtin import create_tools

_SAMPLES = Path(evaluation.__file__).parent / "data" / "built_in_samples.json"


def _attacks() -> list[dict]:
    data = json.loads(_SAMPLES.read_text(encoding="utf-8"))
    return [s for s in data if s.get("scenario_type") == "attack"]


def _orchestrator() -> DialogueOrchestrator:
    # Wire the REAL builtin tools + a query_order route so an unblocked attack
    # WOULD reach a tool — making the "no tool runs" assertion meaningful.
    registry = {t.name: t for t in create_tools()}
    rules = [RoutingRule(intent_patterns=["query_order"], tools=["query_order"])]
    return DialogueOrchestrator(
        security_guard=SecurityGuard({}),
        context_manager=InMemoryContextManager(),
        intent_engine=CascadeIntentEngine(RuleBasedMatcher()),
        tool_injector=ToolInjector(registry=registry, routing_rules=rules),
        strategy=RuleBasedStrategy(),
    )


async def test_all_attack_samples_execute_no_tool() -> None:
    orch = _orchestrator()
    attacks = _attacks()
    assert len(attacks) >= 8
    for s in attacks:
        resp = await orch.handle_message(
            UserMessage(session_id=s["sample_id"], content=s["user_input"], channel="web")
        )
        # The reply is a plain refusal/fallback, never a business rich card, and
        # no tool call is recorded in meta.
        assert resp.message_type == "text", f"{s['sample_id']} -> {resp.message_type}"
        called = resp.meta.get("tools") or resp.meta.get("tool_calls") or []
        assert called == [], f"{s['sample_id']} executed {called}"


def test_attack_samples_encode_no_tool_expectation() -> None:
    attacks = _attacks()
    assert len(attacks) >= 8
    for s in attacks:
        assert s["expected_tool_calls"] == [], s["sample_id"]
