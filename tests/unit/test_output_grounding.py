"""Tests for output grounding — anti-hallucination for money amounts.

Part of the V2.0 semantic-guardrail upgrade (module 4, output side). When the
LLM rewrites a tool result into natural language it can state a refund/price
figure the tool never returned ("凭空发钱"). The grounding check verifies every
money amount the reply mentions is grounded in the tool's own output; the
orchestrator falls back to the deterministic formatted text when it is not.

Two layers are covered:
  - OutputGroundingChecker / SecurityGuard.is_output_grounded — the pure check;
  - DialogueOrchestrator._llm_enhance_tool_result — the wired fallback so a
    hallucinated amount never reaches the user.
"""
from __future__ import annotations

import pytest

from open_chat_shop.core.context import InMemoryContextManager
from open_chat_shop.core.orchestrator import DialogueOrchestrator
from open_chat_shop.core.provider import MockProvider
from open_chat_shop.core.security import OutputGroundingChecker, SecurityGuard
from open_chat_shop.core.types import SessionContext

# ===========================================================================
# OutputGroundingChecker (pure logic)
# ===========================================================================


@pytest.fixture()
def checker() -> OutputGroundingChecker:
    return OutputGroundingChecker()


@pytest.mark.unit
class TestOutputGroundingChecker:
    def test_reply_without_money_is_grounded(self, checker: OutputGroundingChecker) -> None:
        # Most replies (greetings, logistics status) state no money and must
        # pass untouched — the check only scrutinises money.
        assert checker.is_grounded("好的，已经为您安排好了，请耐心等待~", "订单已发货") is True

    def test_grounded_amount_passes(self, checker: OutputGroundingChecker) -> None:
        assert checker.is_grounded(
            "您的退款 ¥199.00 已提交",
            "退款金额：¥199.00",
            "{'refund_amount': 199.0}",
        ) is True

    def test_hallucinated_amount_fails(self, checker: OutputGroundingChecker) -> None:
        # The tool refunded 199 but the LLM "发" 999 — the textbook 凭空发钱.
        assert checker.is_grounded(
            "您的退款 ¥999.00 已到账",
            "退款金额：¥199.00",
            "{'refund_amount': 199.0}",
        ) is False

    def test_value_equality_ignores_trailing_zeros(self, checker: OutputGroundingChecker) -> None:
        # "199元" (reply) is grounded by "199.00" (source): 199 == 199.00.
        assert checker.is_grounded("一共 199元 哦", "总价 199.00") is True

    def test_suffix_and_thousands_separator(self, checker: OutputGroundingChecker) -> None:
        assert checker.is_grounded("合计 1,999 块钱", "{'total': 1999.0}") is True

    def test_one_ungrounded_among_many_fails(self, checker: OutputGroundingChecker) -> None:
        # Says both the real 199 and a fabricated 50 ("额外补偿") — must fail.
        assert checker.is_grounded(
            "退您 ¥199.00，另外补偿 ¥50.00",
            "退款金额：¥199.00",
        ) is False

    def test_dollar_prefix(self, checker: OutputGroundingChecker) -> None:
        assert checker.is_grounded("refund of $20 issued", "amount: 20") is True

    def test_security_guard_exposes_check(self) -> None:
        guard = SecurityGuard({})
        assert guard.is_output_grounded("退您 ¥199.00", "金额 199.00") is True
        assert guard.is_output_grounded("退您 ¥999.00", "金额 199.00") is False


# ===========================================================================
# Orchestrator wiring — hallucinated money never reaches the user
# ===========================================================================


def _bare_orchestrator(provider) -> DialogueOrchestrator:
    """Orchestrator for direct _llm_enhance_tool_result calls.

    Needs a real SecurityGuard (the grounding check lives there); the other
    deps are unused by the enhance helper.
    """
    orch = DialogueOrchestrator(
        security_guard=SecurityGuard({}),
        context_manager=InMemoryContextManager(),
        intent_engine=None,
        tool_injector=None,
        strategy=None,
    )
    orch.set_provider(provider)
    return orch


def _ctx() -> SessionContext:
    return SessionContext(session_id="s1", user_id=None, channel="web")


@pytest.mark.unit
class TestOrchestratorGroundingFallback:
    @pytest.mark.asyncio
    async def test_hallucinated_amount_falls_back_to_formatted(self) -> None:
        # Provider hallucinates ¥999 though the tool refunded ¥199. The enhance
        # helper must reject the text (return None) so the caller uses the
        # grounded formatted string and the 999 never reaches the user.
        provider = MockProvider(default_response="好消息！您的退款 ¥999.00 已经到账啦~")
        orch = _bare_orchestrator(provider)
        text, tokens = await orch._llm_enhance_tool_result(
            "退款金额：¥199.00", {"refund_amount": 199.0}, _ctx()
        )
        assert text is None  # rejected -> caller falls back to formatted
        assert tokens == 30  # the call still happened; cost is still recorded

    @pytest.mark.asyncio
    async def test_grounded_amount_is_kept(self) -> None:
        provider = MockProvider(default_response="您的退款 ¥199.00 已提交，请耐心等待~")
        orch = _bare_orchestrator(provider)
        text, tokens = await orch._llm_enhance_tool_result(
            "退款金额：¥199.00", {"refund_amount": 199.0}, _ctx()
        )
        assert text == "您的退款 ¥199.00 已提交，请耐心等待~"
        assert tokens == 30

    @pytest.mark.asyncio
    async def test_money_free_reply_is_kept(self) -> None:
        provider = MockProvider(default_response="好的，已为您查询到订单信息~")
        orch = _bare_orchestrator(provider)
        text, _ = await orch._llm_enhance_tool_result(
            "订单状态：已发货", {"order_id": "ORD-1", "amount": 199.0}, _ctx()
        )
        assert text == "好的，已为您查询到订单信息~"
