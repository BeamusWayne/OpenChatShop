"""Tests for persona context injection (feat-054, V2.0 module 3).

When a turn is routed to a domain specialist, the user's stored persona tags are
silently appended to that specialist's prompt — "按您上次的习惯推荐" — so the
experience is personalised. Builds on feat-051's _domain_prompt slot. With no
persona repository injected, the prompt is exactly the specialist's (feat-051).
"""
from __future__ import annotations

import pytest

from open_chat_shop.core.context import InMemoryContextManager
from open_chat_shop.core.domain_agents import build_default_agents
from open_chat_shop.core.orchestrator import DialogueOrchestrator
from open_chat_shop.core.security import SecurityGuard
from open_chat_shop.core.triage_router import TriageRouter
from open_chat_shop.core.types import Action, Intent, UserMessage
from open_chat_shop.storage.persona import (
    InMemoryPersonaRepository,
    personalize_prompt,
)


@pytest.mark.unit
class TestPersonalizePrompt:
    def test_appends_persona_tags(self) -> None:
        out = personalize_prompt("你是导购专家。", {"style": "日系简约", "size": "L"})
        assert "你是导购专家。" in out
        assert "日系简约" in out
        assert "L" in out

    def test_empty_persona_returns_base_unchanged(self) -> None:
        assert personalize_prompt("基础", {}) == "基础"
        assert personalize_prompt("基础", None) == "基础"


# --- integration: routed turn picks up the persona ---------------------------


class _StubTool:
    def __init__(self, name: str) -> None:
        self.name = name


class _StubInjector:
    async def inject(self, intent, context):
        return [_StubTool("create_refund"), _StubTool("search_product")]


class _StubIntent:
    async def classify(self, message, context):
        return Intent(name="create_refund", display_name="退款", confidence=1.0, source="rule")


class _ReplyStrategy:
    async def decide(self, intent, context, tools):
        return Action(type="reply", payload={"content": "好的"})


def _orch(*, with_persona: bool):
    orch = DialogueOrchestrator(
        security_guard=SecurityGuard({}),
        context_manager=InMemoryContextManager(),
        intent_engine=_StubIntent(),
        tool_injector=_StubInjector(),
        strategy=_ReplyStrategy(),
    )
    orch.set_triage_router(TriageRouter(build_default_agents()))
    if with_persona:
        repo = InMemoryPersonaRepository()
        repo.upsert("u1", {"style": "日系简约"})
        orch.set_persona_repository(repo)
    return orch


@pytest.mark.unit
class TestPersonaInjectionIntegration:
    @pytest.mark.asyncio
    async def test_routed_turn_injects_persona(self) -> None:
        orch = _orch(with_persona=True)
        await orch.handle_message(
            UserMessage(session_id="s1", content="我要退款", channel="web", user_id="u1")
        )
        ctx = orch._context_manager.get("s1")
        assert "日系简约" in ctx.slots["_domain_prompt"]

    @pytest.mark.asyncio
    async def test_no_persona_repo_uses_plain_domain_prompt(self) -> None:
        orch = _orch(with_persona=False)
        await orch.handle_message(
            UserMessage(session_id="s2", content="我要退款", channel="web", user_id="u1")
        )
        ctx = orch._context_manager.get("s2")
        assert "用户画像" not in ctx.slots["_domain_prompt"]
