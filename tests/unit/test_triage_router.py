"""Tests for TriageRouter (Multi-Agent routing gateway, feat-049).

The Triage gateway is a pure decision component: given the message text, the
already-classified Intent, and the AgentRegistry, it decides whether to hand the
conversation off to a human (extreme negative emotion), route it to a domain
specialist, or fall through. It executes nothing and touches no existing flow —
wiring the decision to the handoff queue / agent execution is feat-051.
"""
from __future__ import annotations

import pytest

from open_chat_shop.core.domain_agent import AgentRegistry, DomainAgent
from open_chat_shop.core.triage_router import (
    TriageDecision,
    TriageRouter,
    detect_escalation,
)
from open_chat_shop.core.types import Intent


def _intent(name: str) -> Intent:
    return Intent(name=name, display_name=name, confidence=1.0, source="rule")


@pytest.fixture()
def registry() -> AgentRegistry:
    reg = AgentRegistry()
    reg.register(
        DomainAgent("refund", ["check_refund_eligibility", "create_refund", "cancel_order"], "售后")
    )
    reg.register(DomainAgent("sales", ["search_product"], "导购"))
    reg.register(DomainAgent("logistics", ["query_order", "query_logistics"], "物流"))
    return reg


@pytest.fixture()
def router(registry: AgentRegistry) -> TriageRouter:
    return TriageRouter(registry)


# ---------------------------------------------------------------------------
# Escalation (negative-emotion) detection
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDetectEscalation:
    @pytest.mark.parametrize(
        "text",
        [
            "我要投诉你们！",
            "再不解决我就去315曝光",
            "我要起诉你们公司",
            "你们就是骗子，我要维权",
            "信不信我找消协和工商局",
            "这种质量退一赔三懂不懂",
        ],
    )
    def test_flags_clear_escalation(self, text: str) -> None:
        assert detect_escalation(text) is True

    @pytest.mark.parametrize(
        "text",
        [
            "这个商品我想查一下物流",
            "我觉得这件衣服质量有点一般",  # 温和不满，不该误转人工
            "帮我看看有没有其他颜色",
            "退款大概多久到账呀",  # 提到退款但不是升级
        ],
    )
    def test_ignores_normal_and_mild(self, text: str) -> None:
        assert detect_escalation(text) is False


# ---------------------------------------------------------------------------
# TriageRouter.triage
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTriageRouter:
    def test_routes_intent_to_owning_domain(self, router: TriageRouter) -> None:
        d = router.triage("帮我查下订单", _intent("query_order"))
        assert d.kind == "route"
        assert d.domain == "logistics"

    def test_routes_refund_intent_to_refund_domain(self, router: TriageRouter) -> None:
        d = router.triage("我要退款", _intent("create_refund"))
        assert d.kind == "route"
        assert d.domain == "refund"

    def test_unknown_intent_falls_back(self, router: TriageRouter) -> None:
        d = router.triage("你好呀", _intent("greeting"))
        assert d.kind == "fallback"
        assert d.domain is None

    def test_escalation_triggers_handoff(self, router: TriageRouter) -> None:
        d = router.triage("我要投诉！", _intent("create_refund"))
        assert d.kind == "handoff"

    def test_emotion_takes_priority_over_routing(self, router: TriageRouter) -> None:
        # Angry customer with a clear routable intent must STILL go to a human —
        # escalation beats domain routing.
        d = router.triage("你们就是骗子，我要起诉，顺便退款", _intent("create_refund"))
        assert d.kind == "handoff"
        assert d.domain is None

    def test_decision_is_immutable(self, router: TriageRouter) -> None:
        d = router.triage("帮我查下订单", _intent("query_order"))
        with pytest.raises((AttributeError, Exception)):
            d.kind = "handoff"  # type: ignore[misc]

    def test_decision_carries_reason(self, router: TriageRouter) -> None:
        assert router.triage("我要投诉", _intent("create_refund")).reason
        assert router.triage("查订单", _intent("query_order")).reason
        assert router.triage("你好", _intent("greeting")).reason


def test_triage_decision_construct() -> None:
    d = TriageDecision(kind="route", domain="sales", reason="intent:search_product")
    assert (d.kind, d.domain, d.reason) == ("route", "sales", "intent:search_product")
