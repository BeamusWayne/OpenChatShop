"""Tests for evaluation framework — golden dataset, regression, LLM judge."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from commerce_agent.evaluation.golden_dataset import GoldenDataset, GoldenSample
from commerce_agent.evaluation.regression import RegressionRunner, RegressionResult
from commerce_agent.evaluation.llm_judge import LLMJudge, JudgeDimension, JudgeResult
from commerce_agent.core.provider import MockProvider


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _make_sample(**overrides) -> GoldenSample:
    """Create a golden sample with sensible defaults."""
    defaults = dict(
        sample_id="GD-001",
        scenario="after_sales",
        intent="request_refund",
        user_input="耳机用了一周就坏了，我要退货",
        expected_intent="request_refund",
        expected_entities={"product_type": "耳机", "issue": "quality"},
        expected_response_contains=["退款", "质量问题"],
        expected_tool_calls=["check_refund_eligibility"],
        risk_level="low",
    )
    defaults.update(overrides)
    return GoldenSample(**defaults)


@pytest.fixture
def sample() -> GoldenSample:
    return _make_sample()


@pytest.fixture
def dataset(sample: GoldenSample) -> GoldenDataset:
    ds = GoldenDataset()
    ds.add_sample(sample)
    ds.add_sample(_make_sample(
        sample_id="GD-002",
        scenario="pre_sales",
        intent="search_product",
        expected_intent="search_product",
        expected_entities={"category": "耳机"},
        expected_response_contains=["搜索"],
        expected_tool_calls=["search_product"],
        risk_level="medium",
    ))
    ds.add_sample(_make_sample(
        sample_id="GD-003",
        scenario="after_sales",
        intent="query_order",
        user_input="查一下我的订单",
        expected_intent="query_order",
        expected_entities={},
        expected_response_contains=["订单"],
        expected_tool_calls=["query_order"],
        risk_level="high",
    ))
    return ds


# ===================================================================
# GoldenDataset tests
# ===================================================================


class TestGoldenDataset:
    """GoldenDataset — add, load, filter, validate."""

    @pytest.mark.unit
    def test_add_sample_and_len(self) -> None:
        ds = GoldenDataset()
        assert len(ds) == 0
        ds.add_sample(_make_sample())
        assert len(ds) == 1

    @pytest.mark.unit
    def test_load_from_dict_valid(self) -> None:
        data = [
            {
                "sample_id": "GD-100",
                "scenario": "after_sales",
                "intent": "request_refund",
                "user_input": "退货",
                "expected_intent": "request_refund",
                "expected_entities": {},
                "expected_response_contains": ["退款"],
                "expected_tool_calls": ["check_refund_eligibility"],
                "risk_level": "low",
            }
        ]
        ds = GoldenDataset()
        ds.load_from_dict(data)
        assert len(ds) == 1
        assert ds.get_by_id("GD-100") is not None

    @pytest.mark.unit
    def test_load_from_json(self) -> None:
        data = [
            {
                "sample_id": "GD-200",
                "scenario": "pre_sales",
                "intent": "search_product",
                "user_input": "找耳机",
                "expected_intent": "search_product",
                "expected_entities": {"category": "耳机"},
                "expected_response_contains": ["搜索"],
                "expected_tool_calls": ["search_product"],
            }
        ]
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump(data, f, ensure_ascii=False)
            path = f.name

        ds = GoldenDataset()
        ds.load_from_json(path)
        assert len(ds) == 1
        assert ds.get_by_id("GD-200") is not None

    @pytest.mark.unit
    def test_get_by_intent(self, dataset: GoldenDataset) -> None:
        results = dataset.get_by_intent("request_refund")
        assert len(results) == 1
        assert results[0].sample_id == "GD-001"

    @pytest.mark.unit
    def test_get_by_scenario(self, dataset: GoldenDataset) -> None:
        results = dataset.get_by_scenario("after_sales")
        assert len(results) == 2  # GD-001 and GD-003

    @pytest.mark.unit
    def test_get_by_risk_level(self, dataset: GoldenDataset) -> None:
        results = dataset.get_by_risk_level("high")
        assert len(results) == 1
        assert results[0].sample_id == "GD-003"

    @pytest.mark.unit
    def test_validate_catches_missing_fields(self) -> None:
        ds = GoldenDataset()
        bad_sample = GoldenSample(
            sample_id="GD-BAD",
            scenario="test",
            intent="test",
            user_input="test",
            expected_intent="test",
            expected_entities={},
            expected_response_contains=[],
            expected_tool_calls=[],
        )
        ds.add_sample(bad_sample)
        errors = ds.validate()
        assert len(errors) > 0
        error_text = " ".join(errors)
        assert "expected_response_contains" in error_text
        assert "expected_tool_calls" in error_text

    @pytest.mark.unit
    def test_validate_catches_invalid_risk_level(self) -> None:
        ds = GoldenDataset()
        ds.add_sample(_make_sample(risk_level="critical"))
        errors = ds.validate()
        assert any("invalid risk_level" in e for e in errors)

    @pytest.mark.unit
    def test_validate_empty_on_valid_dataset(self, dataset: GoldenDataset) -> None:
        errors = dataset.validate()
        assert errors == []

    @pytest.mark.unit
    def test_validate_catches_duplicate_ids(self) -> None:
        ds = GoldenDataset()
        ds.add_sample(_make_sample(sample_id="GD-DUP"))
        ds.add_sample(_make_sample(sample_id="GD-DUP"))
        errors = ds.validate()
        assert any("Duplicate" in e for e in errors)


# ===================================================================
# RegressionRunner tests
# ===================================================================


class TestRegressionRunner:
    """RegressionRunner — compare actual vs expected outputs."""

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_run_single_perfect_match(self, sample: GoldenSample) -> None:
        ds = GoldenDataset()
        ds.add_sample(sample)
        runner = RegressionRunner(ds)
        result = await runner.run_single(
            sample,
            actual_intent="request_refund",
            actual_entities={"product_type": "耳机", "issue": "quality"},
            actual_response="我们为您处理退款，确认是质量问题。",
            actual_tool_calls=["check_refund_eligibility"],
        )
        assert result.passed is True
        assert result.intent_match is True
        assert result.entities_match is True
        assert result.response_contains_match is True
        assert result.tool_calls_match is True
        assert result.errors == []

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_run_single_intent_mismatch(self, sample: GoldenSample) -> None:
        ds = GoldenDataset()
        ds.add_sample(sample)
        runner = RegressionRunner(ds)
        result = await runner.run_single(
            sample,
            actual_intent="query_order",
            actual_entities={"product_type": "耳机", "issue": "quality"},
            actual_response="我们为您处理退款，确认是质量问题。",
            actual_tool_calls=["check_refund_eligibility"],
        )
        assert result.passed is False
        assert result.intent_match is False
        assert any("Intent mismatch" in e for e in result.errors)

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_run_single_partial_entity_match(self, sample: GoldenSample) -> None:
        ds = GoldenDataset()
        ds.add_sample(sample)
        runner = RegressionRunner(ds)
        result = await runner.run_single(
            sample,
            actual_intent="request_refund",
            actual_entities={"product_type": "耳机"},  # missing "issue"
            actual_response="我们为您处理退款，确认是质量问题。",
            actual_tool_calls=["check_refund_eligibility"],
        )
        assert result.passed is False
        assert result.entities_match is False
        assert any("Entities mismatch" in e for e in result.errors)

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_run_single_missing_response_keywords(self, sample: GoldenSample) -> None:
        ds = GoldenDataset()
        ds.add_sample(sample)
        runner = RegressionRunner(ds)
        result = await runner.run_single(
            sample,
            actual_intent="request_refund",
            actual_entities={"product_type": "耳机", "issue": "quality"},
            actual_response="好的，我们帮您处理一下。",  # missing "退款" and "质量问题"
            actual_tool_calls=["check_refund_eligibility"],
        )
        assert result.passed is False
        assert result.response_contains_match is False
        assert any("missing keywords" in e for e in result.errors)

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_run_single_missing_tool_calls(self, sample: GoldenSample) -> None:
        ds = GoldenDataset()
        ds.add_sample(sample)
        runner = RegressionRunner(ds)
        result = await runner.run_single(
            sample,
            actual_intent="request_refund",
            actual_entities={"product_type": "耳机", "issue": "quality"},
            actual_response="我们为您处理退款，确认是质量问题。",
            actual_tool_calls=[],  # missing expected tool
        )
        assert result.passed is False
        assert result.tool_calls_match is False
        assert any("Missing tool calls" in e for e in result.errors)

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_run_batch_multiple_results(self, dataset: GoldenDataset) -> None:
        runner = RegressionRunner(dataset)
        batch_input = [
            (
                "GD-001",
                "request_refund",
                {"product_type": "耳机", "issue": "quality"},
                "退款处理中，确认是质量问题。",
                ["check_refund_eligibility"],
            ),
            (
                "GD-002",
                "search_product",
                {"category": "耳机"},
                "为您搜索到相关商品。",
                ["search_product"],
            ),
        ]
        results = await runner.run_batch(batch_input)
        assert len(results) == 2
        assert results[0].passed is True
        assert results[1].passed is True

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_run_batch_unknown_sample_id(self, dataset: GoldenDataset) -> None:
        runner = RegressionRunner(dataset)
        batch_input = [
            ("GD-999", "whatever", {}, "response", []),
        ]
        results = await runner.run_batch(batch_input)
        assert len(results) == 1
        assert results[0].passed is False
        assert any("not found" in e for e in results[0].errors)

    @pytest.mark.unit
    def test_generate_report_calculates_correctly(self) -> None:
        ds = GoldenDataset()
        runner = RegressionRunner(ds)
        results = [
            RegressionResult(
                sample_id="A", passed=True,
                intent_match=True, entities_match=True,
                response_contains_match=True, tool_calls_match=True,
            ),
            RegressionResult(
                sample_id="B", passed=False,
                intent_match=True, entities_match=False,
                response_contains_match=True, tool_calls_match=True,
            ),
            RegressionResult(
                sample_id="C", passed=False,
                intent_match=False, entities_match=True,
                response_contains_match=True, tool_calls_match=True,
            ),
        ]
        report = runner.generate_report(results)
        assert report["total"] == 3
        assert report["passed"] == 1
        assert report["failed"] == 2
        assert report["pass_rate"] == round(1 / 3, 4)
        assert report["intent_accuracy"] == round(2 / 3, 4)

    @pytest.mark.unit
    def test_generate_report_empty_results(self) -> None:
        ds = GoldenDataset()
        runner = RegressionRunner(ds)
        report = runner.generate_report([])
        assert report["total"] == 0
        assert report["pass_rate"] == 0.0


# ===================================================================
# LLMJudge tests
# ===================================================================


class TestLLMJudge:
    """LLMJudge — multi-dimensional quality scoring with mock provider."""

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_evaluate_returns_four_results(self) -> None:
        provider = MockProvider(default_response="Score: 4\nReasoning: Good response")
        judge = LLMJudge(provider)
        results = await judge.evaluate("帮我退款", "好的，正在处理退款。")
        assert len(results) == 4
        names = [r.dimension for r in results]
        assert names == ["accuracy", "safety", "helpfulness", "tone"]

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_score_parsing(self) -> None:
        provider = MockProvider(default_response="Score: 5\nReasoning: Excellent")
        judge = LLMJudge(provider)
        results = await judge.evaluate("hello", "hi")
        assert all(r.score == 5 for r in results)
        assert all(r.reasoning == "Excellent" for r in results)

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_fail_threshold_flags_failures(self) -> None:
        provider = MockProvider(default_response="Score: 3\nReasoning: Could be better")
        judge = LLMJudge(provider)
        results = await judge.evaluate("test", "response")
        safety = next(r for r in results if r.dimension == "safety")
        assert safety.passed is False
        assert safety.score == 3

        accuracy = next(r for r in results if r.dimension == "accuracy")
        assert accuracy.passed is True

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_custom_dimensions(self) -> None:
        provider = MockProvider(default_response="Score: 5\nReasoning: Perfect")
        custom = [
            JudgeDimension(name="empathy", prompt="Is the response empathetic?"),
            JudgeDimension(name="conciseness", prompt="Is the response concise?"),
        ]
        judge = LLMJudge(provider, dimensions=custom)
        results = await judge.evaluate("input", "output")
        assert len(results) == 2
        assert results[0].dimension == "empathy"
        assert results[1].dimension == "conciseness"

    @pytest.mark.unit
    def test_judge_prompt_construction(self) -> None:
        provider = MockProvider()
        judge = LLMJudge(provider)
        dim = JudgeDimension(name="test_dim", prompt="Test criteria?")
        prompt = judge._build_judge_prompt(dim, "user question", "agent answer", "ctx info")
        assert "test_dim" in prompt
        assert "Test criteria?" in prompt
        assert "user question" in prompt
        assert "agent answer" in prompt
        assert "ctx info" in prompt
        assert "Score:" in prompt
        assert "Reasoning:" in prompt

    @pytest.mark.unit
    def test_judge_prompt_without_context(self) -> None:
        provider = MockProvider()
        judge = LLMJudge(provider)
        dim = JudgeDimension(name="x", prompt="y")
        prompt = judge._build_judge_prompt(dim, "q", "a", "")
        assert "Context:" not in prompt

    @pytest.mark.unit
    def test_parse_response_handles_various_formats(self) -> None:
        score, reason = LLMJudge._parse_response("Score: 4\nReasoning: Looks good")
        assert score == 4
        assert reason == "Looks good"

        score, reason = LLMJudge._parse_response("score: 2\nreasoning: Bad")
        assert score == 2
        assert reason == "Bad"

        score, reason = LLMJudge._parse_response("Score: 3")
        assert score == 3
        assert reason == ""

        score, reason = LLMJudge._parse_response("No score here")
        assert score == 1

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_evaluate_with_context(self) -> None:
        provider = MockProvider(default_response="Score: 5\nReasoning: Great")
        judge = LLMJudge(provider)
        results = await judge.evaluate(
            "退款", "好的退款", context="用户之前买过耳机"
        )
        assert len(results) == 4
        assert len(provider.call_log) == 4
