
# remediation workflow (one file per CLUSTER, uppercase cluster id) to avoid
# collisions between parallel agents; the module name is intentional.
"""Audit regression tests for the INTENT cluster.

Each test pins a behaviour-changing bug fix in
``open_chat_shop.core.intent`` / ``open_chat_shop.core.strategy``. The
docstrings record the pre-fix (RED) behaviour so the intent of the test is
auditable, per project Rule 9.

Findings covered:
  - HIGH-1  leftover context slots / internal flags leak into strict tool
            schemas and fail ``additionalProperties: False`` validation.
  - HIGH-2  ``create_refund`` intent ran ``check_refund_eligibility`` because
            the strategy blindly used ``tools[0]``.
  - MEDIUM  Level-2 semantic search re-tokenised every sample on every call.
  - LOW-1   ``confirmation_threshold`` (amount > 500) was dead config.
  - LOW-2   product keyword extraction captured noise / mis-extracted bare
            trigger words ("搜索" -> "索").
"""
from __future__ import annotations

from typing import Any

import pytest

from open_chat_shop.core.intent import (
    CascadeIntentEngine,
    RuleBasedMatcher,
    _clean_keyword,
    _extract_entities,
)
from open_chat_shop.core.strategy import RuleBasedStrategy
from open_chat_shop.core.types import (
    Intent,
    SessionContext,
    ToolPermission,
)
from open_chat_shop.tools.builtin.check_refund_eligibility import (
    CheckRefundEligibilityTool,
)
from open_chat_shop.tools.builtin.create_refund import CreateRefundTool
from open_chat_shop.tools.builtin.search_product import SearchProductTool


def _ctx(**overrides: Any) -> SessionContext:
    defaults: dict[str, Any] = dict(session_id="s1", user_id="u1", channel="web")
    defaults.update(overrides)
    return SessionContext(**defaults)


def _intent(name: str, **entities: Any) -> Intent:
    return Intent(
        name=name,
        display_name=name,
        confidence=1.0,
        source="rule",
        entities=dict(entities),
    )


# ===========================================================================
# HIGH-1 — context slots / internal flags must not break strict tool schemas
# ===========================================================================


class TestHigh1ParamWhitelisting:
    """RED before fix: ``RuleBasedStrategy.decide`` did ``params =
    dict(intent.entities)`` and passed every persisted slot + the
    ``_clarifying_response`` flag to ``tool.validate``. Built-in schemas set
    ``additionalProperties: False``, so a valid call carrying a stale
    ``order_id`` slot was rejected and the user was wrongly told their info was
    incomplete."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_stale_slot_does_not_leak_into_search_params(self) -> None:
        strategy = RuleBasedStrategy()
        tool = SearchProductTool()
        # keyword is valid; order_id is a stale slot from a prior order query;
        # _clarifying_response is an internal flag from the intent engine.
        intent = _intent(
            "search_product",
            keyword="耳机",
            order_id="ORD-123",
            _clarifying_response=True,
        )

        action = await strategy.decide(intent, _ctx(), [tool])

        assert action.type == "tool_call"
        # Only the schema-declared keyword survives.
        assert action.payload["params"] == {"keyword": "耳机"}
        # And it actually passes the strict schema (the bug surfaced here).
        validation = tool.validate(action.payload["params"])
        assert validation.valid is True
        assert validation.errors == []

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_internal_flag_stripped_even_when_only_extra(self) -> None:
        strategy = RuleBasedStrategy()
        tool = SearchProductTool()
        intent = _intent("search_product", keyword="鼠标", _clarifying_response=True)

        action = await strategy.decide(intent, _ctx(), [tool])

        assert "_clarifying_response" not in action.payload["params"]
        assert tool.validate(action.payload["params"]).valid is True

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_real_missing_param_still_detected_after_filtering(self) -> None:
        """Filtering must not mask a genuinely missing required param: a stale
        order_id slot must not satisfy search_product's required ``keyword``."""
        strategy = RuleBasedStrategy()
        tool = SearchProductTool()
        intent = _intent("search_product", order_id="ORD-123")

        action = await strategy.decide(intent, _ctx(), [tool])

        assert action.type == "clarify"
        assert "keyword" in action.payload["missing_slots"]


# ===========================================================================
# HIGH-2 — create_refund intent must run create_refund, not the eligibility read
# ===========================================================================


class TestHigh2ToolSelection:
    """RED before fix: the refund routing rule injects
    ``[check_refund_eligibility, create_refund]`` (in that order) and
    ``decide`` used ``tools[0]``, so an explicit ``create_refund`` intent ran
    the idempotent eligibility check and the refund was never created."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_create_refund_intent_selects_create_refund_tool(self) -> None:
        strategy = RuleBasedStrategy()
        # Injector order from configs/tool_routing.yaml.
        tools = [CheckRefundEligibilityTool(), CreateRefundTool()]
        intent = _intent("create_refund", order_id="ORD-1", reason="坏了", amount=600)

        action = await strategy.decide(intent, _ctx(), tools)

        # High amount -> confirm; the gated tool must be create_refund.
        assert action.type == "confirm"
        assert action.payload["pending_action"]["tool_name"] == "create_refund"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_falls_back_to_first_tool_when_no_name_match(self) -> None:
        """When no injected tool matches the intent name, behaviour is
        unchanged: the first tool is used (preserves the legacy ``refund``
        intent path)."""
        strategy = RuleBasedStrategy()
        tools = [CheckRefundEligibilityTool(), CreateRefundTool()]
        intent = _intent("refund", order_id="ORD-1")

        action = await strategy.decide(intent, _ctx(), tools)

        # check_refund_eligibility only requires order_id -> a tool_call.
        assert action.type == "tool_call"
        assert action.payload["tool_name"] == "check_refund_eligibility"


# ===========================================================================
# LOW-1 — confirmation_threshold gates confirmation
# ===========================================================================


class TestLow1ConfirmationThreshold:
    """RED before fix: ``decide`` triggered confirmation purely on
    ``requires_confirmation`` and never read ``confirmation_threshold``, so a
    10-yuan refund demanded confirmation just like a 5000-yuan one."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_small_amount_below_threshold_skips_confirmation(self) -> None:
        strategy = RuleBasedStrategy()
        tools = [CreateRefundTool()]
        intent = _intent("create_refund", order_id="ORD-1", reason="x", amount=10)

        action = await strategy.decide(intent, _ctx(), tools)

        # amount 10 <= 500 -> no confirmation gate, execute directly.
        assert action.type == "tool_call"
        assert action.payload["tool_name"] == "create_refund"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_large_amount_above_threshold_requires_confirmation(self) -> None:
        strategy = RuleBasedStrategy()
        tools = [CreateRefundTool()]
        intent = _intent("create_refund", order_id="ORD-1", reason="x", amount=600)

        action = await strategy.decide(intent, _ctx(), tools)

        assert action.type == "confirm"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_missing_amount_requires_confirmation_safe_side(self) -> None:
        """If amount is unknown the true refund could exceed the bound, so the
        gate stays on (safe-side)."""
        strategy = RuleBasedStrategy()
        tools = [CreateRefundTool()]
        intent = _intent("create_refund", order_id="ORD-1", reason="x")

        action = await strategy.decide(intent, _ctx(), tools)

        assert action.type == "confirm"

    @pytest.mark.unit
    def test_no_threshold_means_unconditional_confirmation(self) -> None:
        """Tools without a threshold keep the original unconditional gate."""
        perms = ToolPermission(requires_confirmation=True)
        assert RuleBasedStrategy._needs_confirmation(perms, {"amount": 1}) is True

    @pytest.mark.unit
    def test_no_confirmation_flag_never_gates(self) -> None:
        perms = ToolPermission(requires_confirmation=False)
        assert RuleBasedStrategy._needs_confirmation(perms, {"amount": 9999}) is False


# ===========================================================================
# LOW-2 — keyword extraction noise / bare-trigger mis-extraction
# ===========================================================================


class TestLow2KeywordExtraction:
    """RED before fix: ``搜索?`` made the second 索 optional so a bare "搜索"
    captured "索"; trailing price phrases and leading quantifiers were kept."""

    @pytest.mark.unit
    def test_bare_trigger_word_yields_no_keyword(self) -> None:
        # The core bug: "搜索" must not search for the meaningless "索".
        assert _extract_entities("搜索", "search_product") == {}

    @pytest.mark.unit
    def test_other_bare_triggers_yield_no_keyword(self) -> None:
        assert _extract_entities("查找", "search_product") == {}
        assert _extract_entities("找", "search_product") == {}

    @pytest.mark.unit
    def test_trailing_price_phrase_stripped(self) -> None:
        result = _extract_entities("帮我找一下充电器多少钱", "search_product")
        assert result == {"keyword": "充电器"}

    @pytest.mark.unit
    def test_leading_quantifier_stripped(self) -> None:
        result = _extract_entities("我想买一个手机壳", "search_product")
        assert result == {"keyword": "手机壳"}

    @pytest.mark.unit
    def test_normal_keyword_unaffected(self) -> None:
        assert _extract_entities("搜索耳机", "search_product") == {"keyword": "耳机"}
        assert _extract_entities("查找蓝牙音箱", "search_product") == {
            "keyword": "蓝牙音箱"
        }

    @pytest.mark.unit
    def test_clean_keyword_returns_none_for_noise_only(self) -> None:
        assert _clean_keyword("多少钱") is None
        assert _clean_keyword("   ") is None


# ===========================================================================
# MEDIUM — sample token sets are precomputed, not rebuilt per classification
# ===========================================================================


class TestMediumSampleTokenCaching:
    """RED before fix: ``_semantic_search`` called ``self._tokenize(sample)``
    inside the per-call loop, rebuilding every sample's token set on every
    message. After the fix sample token sets are precomputed in
    ``add_samples`` and only the incoming query is tokenised per call."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_sample_tokens_precomputed_on_add(self) -> None:
        engine = CascadeIntentEngine(RuleBasedMatcher())
        await engine.add_samples("query_order", ["查询订单", "订单状态"])

        # Precomputed cache mirrors the stored samples.
        assert "query_order" in engine._sample_tokens
        assert len(engine._sample_tokens["query_order"]) == 2
        # The cached token set matches a fresh tokenisation of the sample.
        assert engine._sample_tokens["query_order"][0] == engine._tokenize("查询订单")

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_search_does_not_retokenize_samples(self, monkeypatch) -> None:
        """``_semantic_search`` must tokenise only the query, never the samples,
        on each call. We count ``_tokenize`` calls: with 3 cached samples a
        single classification should tokenise exactly once (the query)."""
        engine = CascadeIntentEngine(
            RuleBasedMatcher(), level1_threshold=0.99, level2_threshold=0.1
        )
        await engine.add_samples("query_order", ["查询订单", "订单状态", "我的订单"])

        calls = {"n": 0}
        # Accessing a staticmethod via the class yields the underlying function.
        original = CascadeIntentEngine._tokenize

        def counting_tokenize(text: str) -> set[str]:
            calls["n"] += 1
            return original(text)

        monkeypatch.setattr(
            CascadeIntentEngine, "_tokenize", staticmethod(counting_tokenize)
        )

        result = await engine._semantic_search("查询我的订单")

        # Exactly one tokenise call (the query) despite 3 samples.
        assert calls["n"] == 1
        assert result is not None
        assert result.name == "query_order"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_caching_preserves_semantic_match(self) -> None:
        """Behaviour parity: caching must not change which intent wins."""
        engine = CascadeIntentEngine(
            RuleBasedMatcher(), level1_threshold=0.99, level2_threshold=0.1
        )
        await engine.add_samples("query_order", ["查询订单", "订单状态"])
        await engine.add_samples("refund", ["退款申请", "申请退货"])

        result = await engine._semantic_search("我想查询订单")
        assert result is not None
        assert result.name == "query_order"
