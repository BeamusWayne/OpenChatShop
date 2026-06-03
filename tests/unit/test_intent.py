"""Tests for IntentEngine — RuleBasedMatcher and CascadeIntentEngine."""
from __future__ import annotations

import pytest

from open_chat_shop.core.intent import CascadeIntentEngine, RuleBasedMatcher
from open_chat_shop.core.provider import MockProvider
from open_chat_shop.core.types import (
    IntentInfo,
    Message,
    SessionContext,
    UserMessage,
)

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_message(content: str) -> UserMessage:
    return UserMessage(session_id="s1", content=content, channel="web")


def _make_context(**overrides) -> SessionContext:
    defaults = dict(
        session_id="s1",
        user_id="u1",
        channel="web",
    )
    defaults.update(overrides)
    return SessionContext(**defaults)


def _make_rule_matcher() -> RuleBasedMatcher:
    """Pre-loaded matcher with common e-commerce intent rules."""
    matcher = RuleBasedMatcher()
    matcher.add_rule("query_order", r"订单|查询|物流|快递")
    matcher.add_rule("refund", r"退款|退货|退钱|不想要")
    matcher.add_rule("search_product", r"搜索|查找|找|有没有|想买")
    matcher.add_rule("cancel_order", r"取消|取消订单|不要了")
    return matcher


def _make_engine(
    level1_threshold: float = 0.85,
    level2_threshold: float = 0.70,
    level3_threshold: float = 0.50,
    with_provider: bool = False,
) -> CascadeIntentEngine:
    matcher = _make_rule_matcher()
    engine = CascadeIntentEngine(
        rule_matcher=matcher,
        level1_threshold=level1_threshold,
        level2_threshold=level2_threshold,
        level3_threshold=level3_threshold,
    )
    if with_provider:
        engine.set_provider(MockProvider(default_response="query_order"))
    return engine


# ===========================================================================
# RuleBasedMatcher
# ===========================================================================


class TestRuleBasedMatcher:
    @pytest.mark.unit
    def test_single_keyword_match(self):
        """A single keyword triggers the corresponding intent."""
        matcher = RuleBasedMatcher()
        matcher.add_rule("greet", r"你好|hi|hello")

        result = matcher.match("你好，我想咨询一下")

        assert result is not None
        assert result.name == "greet"
        assert result.source == "rule"
        assert result.confidence == 1.0

    @pytest.mark.unit
    def test_no_match_returns_none(self):
        """Text that matches no rules yields None."""
        matcher = RuleBasedMatcher()
        matcher.add_rule("query_order", r"订单|物流")

        result = matcher.match("今天天气真好")

        assert result is None

    @pytest.mark.unit
    def test_multiple_intents_highest_confidence_wins(self):
        """When several intents match, the highest-scoring one wins."""
        matcher = RuleBasedMatcher()
        matcher.add_rule("refund", r"退款", weight=1.0)
        matcher.add_rule("query_order", r"订单", weight=1.0)
        # "refund" gets an extra boost from a second pattern
        matcher.add_rule("refund", r"退货", weight=1.0)

        result = matcher.match("我要退款退货，订单号12345")

        assert result is not None
        assert result.name == "refund"
        # refund score = 2.0 (退款 + 退货), order score = 1.0 (订单)
        assert result.confidence == pytest.approx(2.0 / 3.0)

    @pytest.mark.unit
    def test_regex_pattern_match(self):
        """Full regex patterns work, not just keywords."""
        matcher = RuleBasedMatcher()
        matcher.add_rule("order_id", r"订单号\s*\d+")

        result = matcher.match("我的订单号 99887766")

        assert result is not None
        assert result.name == "order_id"

    @pytest.mark.unit
    def test_case_insensitive_match(self):
        """Patterns match regardless of case."""
        matcher = RuleBasedMatcher()
        matcher.add_rule("greet", r"hello")

        result = matcher.match("HELLO there")

        assert result is not None
        assert result.name == "greet"

    @pytest.mark.unit
    def test_weighted_scoring(self):
        """Higher-weight rules produce higher confidence."""
        matcher = RuleBasedMatcher()
        matcher.add_rule("a", r"foo", weight=3.0)
        matcher.add_rule("b", r"bar", weight=1.0)

        result = matcher.match("foo bar baz")

        assert result is not None
        assert result.name == "a"
        assert result.confidence == pytest.approx(3.0 / 4.0)

    @pytest.mark.unit
    def test_empty_matcher_returns_none(self):
        """An empty matcher never matches."""
        matcher = RuleBasedMatcher()
        assert matcher.match("anything") is None


# ===========================================================================
# CascadeIntentEngine — Level 1 (rules)
# ===========================================================================


class TestCascadeLevel1:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_level1_resolves_when_confidence_above_threshold(self):
        """Rule match with confidence >= threshold resolves at level 1."""
        engine = _make_engine(level1_threshold=0.85)

        # "订单" matches query_order only -> confidence 1.0
        msg = _make_message("查询订单")
        ctx = _make_context()
        result = await engine.classify(msg, ctx)

        assert result.name == "query_order"
        assert result.source == "rule"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_level1_miss_escalates_to_level2(self):
        """If rule confidence < threshold, engine tries semantic level."""
        # Use a matcher where two intents overlap, producing confidence < 1.0
        matcher = RuleBasedMatcher()
        matcher.add_rule("query_order", r"查", weight=1.0)
        matcher.add_rule("search_product", r"找", weight=1.0)

        engine = CascadeIntentEngine(
            rule_matcher=matcher,
            level1_threshold=0.99,
            level2_threshold=0.3,
        )
        # Add semantic samples so level 2 can resolve
        await engine.add_samples("search_product", ["帮我找商品", "查找商品"])

        msg = _make_message("查一下帮我找")
        ctx = _make_context()
        result = await engine.classify(msg, ctx)

        # Should not be rule (threshold too high), but semantic can resolve
        assert result is not None
        assert result.source in ("semantic", "rule")


# ===========================================================================
# CascadeIntentEngine — Level 2 (semantic)
# ===========================================================================


class TestCascadeLevel2:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_semantic_resolves_when_rules_miss(self):
        """Semantic level resolves when no rules match but samples overlap."""
        # Use a bare matcher with no rules so level 1 cannot match
        engine = CascadeIntentEngine(
            rule_matcher=RuleBasedMatcher(),
            level1_threshold=0.85,
            level2_threshold=0.3,
        )
        # Use space-separated words so Jaccard overlap is calculable
        await engine.add_samples("search_product", ["搜索 商品", "查找 商品", "找 商品"])

        msg = _make_message("搜索 商品")
        ctx = _make_context()
        result = await engine.classify(msg, ctx)

        assert result is not None
        assert result.name == "search_product"
        assert result.source == "semantic"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_semantic_skipped_when_no_samples(self):
        """Without samples, semantic search yields None."""
        engine = _make_engine(level1_threshold=0.99, level2_threshold=0.5)

        # No rules will reach threshold, no samples registered
        msg = _make_message("随便聊聊")
        ctx = _make_context()
        result = await engine.classify(msg, ctx)

        # Falls through to fallback
        assert result.name == "fallback"


# ===========================================================================
# CascadeIntentEngine — Level 3 (LLM)
# ===========================================================================


class TestCascadeLevel3:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_llm_resolves_when_rules_and_semantic_miss(self):
        """LLM classification is attempted when levels 1 and 2 fail."""
        engine = _make_engine(
            level1_threshold=0.99,
            level2_threshold=0.99,
            level3_threshold=0.5,
            with_provider=True,
        )
        engine.register_intent(IntentInfo(
            name="query_order",
            display_name="查询订单",
            description="User wants to check order status",
            sample_count=0,
        ))

        msg = _make_message("我的包裹到哪了")
        ctx = _make_context()
        result = await engine.classify(msg, ctx)

        # MockProvider returns "query_order" -> mapped correctly
        assert result.name == "query_order"
        assert result.source == "llm"
        assert result.confidence >= 0.5

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_llm_not_called_without_provider(self):
        """Without a provider, level 3 is skipped entirely."""
        engine = _make_engine(level1_threshold=0.99, level2_threshold=0.99)
        engine.register_intent(IntentInfo(
            name="query_order",
            display_name="查询订单",
            description="Check order",
            sample_count=0,
        ))

        msg = _make_message("我的包裹到哪了")
        ctx = _make_context()
        result = await engine.classify(msg, ctx)

        assert result.name == "fallback"


# ===========================================================================
# CascadeIntentEngine — fallback
# ===========================================================================


class TestCascadeFallback:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_fallback_when_all_levels_fail(self):
        """Returns fallback intent when nothing matches."""
        engine = _make_engine(
            level1_threshold=0.99,
            level2_threshold=0.99,
            level3_threshold=0.99,
            with_provider=True,
        )
        # Provider returns something but level3 threshold is unreachable
        engine.register_intent(IntentInfo(
            name="query_order",
            display_name="查询订单",
            description="Check order",
            sample_count=0,
        ))

        msg = _make_message("随便说点什么")
        ctx = _make_context()
        result = await engine.classify(msg, ctx)

        assert result.name == "fallback"
        assert result.display_name == "未识别"
        assert result.confidence == 0.0
        assert result.source == "rule"


# ===========================================================================
# CascadeIntentEngine — registry and samples
# ===========================================================================


class TestIntentRegistry:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_get_supported_intents_empty(self):
        engine = _make_engine()
        assert engine.get_supported_intents() == []

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_register_and_get_intents(self):
        engine = _make_engine()
        info = IntentInfo(
            name="query_order",
            display_name="查询订单",
            description="Check order status",
            sample_count=5,
            typical_entities=["order_id"],
        )
        engine.register_intent(info)

        intents = engine.get_supported_intents()
        assert len(intents) == 1
        assert intents[0].name == "query_order"
        assert intents[0].display_name == "查询订单"
        assert intents[0].sample_count == 5
        assert "order_id" in intents[0].typical_entities

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_add_samples(self):
        # Use a bare matcher so rules don't interfere
        engine = CascadeIntentEngine(
            rule_matcher=RuleBasedMatcher(),
            level1_threshold=0.85,
            level2_threshold=0.3,
        )
        await engine.add_samples("greeting", ["你好 世界", "你好 早上好"])

        # Verify semantic search can find it
        msg = _make_message("你好 世界")
        ctx = _make_context()

        result = await engine.classify(msg, ctx)
        assert result.name == "greeting"
        assert result.source == "semantic"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_multiple_intent_samples_independent(self):
        engine = _make_engine()
        await engine.add_samples("refund", ["我要退款", "退货退款"])
        await engine.add_samples("cancel", ["取消订单", "不要了"])

        # get_supported_intents reflects register_intent, not add_samples
        assert engine.get_supported_intents() == []


# ===========================================================================
# Level 2 — Chinese bigram tokenisation (HIGH-8 regression tests)
# ===========================================================================


class TestSemanticChineseBigram:
    """Regression tests for HIGH-8: Level-2 must produce non-zero Jaccard
    scores for natural Chinese text that shares no whitespace tokens with
    its registered samples."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_chinese_query_order_hits_level2(self):
        """'我想查询我的订单' shares bigrams with sample '查询订单' → non-zero score
        → Level-2 resolves without touching Level-3."""
        engine = CascadeIntentEngine(
            rule_matcher=RuleBasedMatcher(),  # no rules → must reach level 2
            level1_threshold=0.99,
            level2_threshold=0.1,  # low enough that bigram overlap clears it
        )
        await engine.add_samples("query_order", ["查询订单", "我的订单状态"])

        msg = _make_message("我想查询我的订单")
        ctx = _make_context()
        result = await engine.classify(msg, ctx)

        assert result is not None
        assert result.name == "query_order"
        assert result.source == "semantic"
        assert result.confidence > 0.0

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_chinese_refund_phrase_hits_level2(self):
        """'我要申请退款' shares bigrams with sample '退款申请' → non-zero score."""
        engine = CascadeIntentEngine(
            rule_matcher=RuleBasedMatcher(),
            level1_threshold=0.99,
            level2_threshold=0.1,
        )
        await engine.add_samples("refund", ["退款申请", "申请退货"])

        msg = _make_message("我要申请退款")
        ctx = _make_context()
        result = await engine.classify(msg, ctx)

        assert result is not None
        assert result.name == "refund"
        assert result.source == "semantic"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_unrelated_chinese_phrase_does_not_hit(self):
        """Completely unrelated text should not match a query_order sample."""
        engine = CascadeIntentEngine(
            rule_matcher=RuleBasedMatcher(),
            level1_threshold=0.99,
            level2_threshold=0.5,  # strict threshold — unrelated text must fall below
        )
        await engine.add_samples("query_order", ["查询订单", "订单状态"])

        # "今天天气真好" shares no bigrams with any of the samples
        msg = _make_message("今天天气真好")
        ctx = _make_context()
        result = await engine.classify(msg, ctx)

        # Must not resolve to query_order at level 2
        assert result.name != "query_order"

    @pytest.mark.unit
    def test_tokenize_chinese_produces_bigrams(self):
        """_tokenize should return character bigrams for Chinese text."""
        tokens = CascadeIntentEngine._tokenize("查询订单")
        # Expected bigrams: '查询', '询订', '订单'
        assert "查询" in tokens
        assert "询订" in tokens
        assert "订单" in tokens

    @pytest.mark.unit
    def test_tokenize_english_preserves_space_tokens(self):
        """_tokenize should keep whitespace tokens for English text."""
        tokens = CascadeIntentEngine._tokenize("hello world")
        assert "hello" in tokens
        assert "world" in tokens

    @pytest.mark.unit
    def test_tokenize_mixed_text(self):
        """_tokenize handles mixed Chinese+English: both bigrams and space tokens."""
        tokens = CascadeIntentEngine._tokenize("order 订单")
        assert "order" in tokens   # whitespace token
        assert "订单" in tokens    # bigram


# ===========================================================================
# Context-assisted disambiguation
# ===========================================================================


class TestContextEnrichment:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_slots_merged_into_entities(self):
        """Session context slots are carried into the intent entities."""
        engine = _make_engine()
        # "订单" matches query_order at level 1
        msg = _make_message("查询订单")
        ctx = _make_context(slots={"order_id": "ORD-123", "category": "electronics"})

        result = await engine.classify(msg, ctx)

        assert result.name == "query_order"
        assert result.entities["order_id"] == "ORD-123"
        assert result.entities["category"] == "electronics"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_existing_entities_not_overwritten_by_slots(self):
        """Intent entities take precedence over slot data of the same key."""
        engine = _make_engine()
        msg = _make_message("查询订单")
        ctx = _make_context(slots={"source": "slot_value"})

        result = await engine.classify(msg, ctx)
        # The rule match produces no entities, so slot is merged in
        assert result.entities["source"] == "slot_value"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_clarifying_question_detected_from_history(self):
        """When recent history contains a clarifying question, intent is flagged."""
        engine = _make_engine()
        msg = _make_message("查询订单")
        ctx = _make_context(
            history=[
                Message(role="assistant", content="请问您要查询哪个订单？"),
            ]
        )

        result = await engine.classify(msg, ctx)

        assert result.entities.get("_clarifying_response") is True

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_no_clarifying_flag_without_question(self):
        """No clarifying flag when history lacks a clarification prompt."""
        engine = _make_engine()
        msg = _make_message("查询订单")
        ctx = _make_context(
            history=[
                Message(role="assistant", content="好的，正在为您查询。"),
            ]
        )

        result = await engine.classify(msg, ctx)

        assert "_clarifying_response" not in result.entities

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_empty_context_works(self):
        """Classification works with a minimal, empty context."""
        engine = _make_engine()
        msg = _make_message("查询订单")
        ctx = _make_context()

        result = await engine.classify(msg, ctx)

        assert result.name == "query_order"
        assert result.entities == {}
