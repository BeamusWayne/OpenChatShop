"""Regression test runner — compares actual vs expected outputs."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from open_chat_shop.evaluation.golden_dataset import GoldenDataset, GoldenSample


@dataclass(frozen=True)
class RegressionResult:
    """Result of running a single sample through the regression checker."""

    sample_id: str
    passed: bool
    intent_match: bool
    entities_match: bool
    response_contains_match: bool
    tool_calls_match: bool
    errors: list[str] = field(default_factory=list)


class RegressionRunner:
    """Compare actual agent outputs against golden sample expectations."""

    def __init__(self, dataset: GoldenDataset) -> None:
        self._dataset = dataset

    async def run_single(
        self,
        sample: GoldenSample,
        actual_intent: str,
        actual_entities: dict[str, Any],
        actual_response: str,
        actual_tool_calls: list[str],
    ) -> RegressionResult:
        """Compare actual values against a single golden sample."""
        errors: list[str] = []

        # Intent: exact string match
        intent_match = actual_intent == sample.expected_intent
        if not intent_match:
            errors.append(
                f"Intent mismatch: expected '{sample.expected_intent}', "
                f"got '{actual_intent}'"
            )

        # Entities: all expected keys present with matching values
        entities_match = _entities_match(sample.expected_entities, actual_entities)
        if not entities_match:
            errors.append(
                f"Entities mismatch: expected {sample.expected_entities}, "
                f"got {actual_entities}"
            )

        # Response: all expected substrings present
        missing_keywords = [
            kw for kw in sample.expected_response_contains
            if kw not in actual_response
        ]
        response_contains_match = len(missing_keywords) == 0
        if missing_keywords:
            errors.append(
                f"Response missing keywords: {missing_keywords}"
            )

        # Tool calls: all expected tools called
        missing_tools = [
            t for t in sample.expected_tool_calls
            if t not in actual_tool_calls
        ]
        tool_calls_match = len(missing_tools) == 0
        if missing_tools:
            errors.append(
                f"Missing tool calls: {missing_tools}"
            )

        passed = intent_match and entities_match and response_contains_match and tool_calls_match

        return RegressionResult(
            sample_id=sample.sample_id,
            passed=passed,
            intent_match=intent_match,
            entities_match=entities_match,
            response_contains_match=response_contains_match,
            tool_calls_match=tool_calls_match,
            errors=errors,
        )

    async def run_batch(
        self,
        results: list[tuple[str, str, dict[str, Any], str, list[str]]],
    ) -> list[RegressionResult]:
        """Run regression for a batch of (sample_id, intent, entities, response, tools)."""
        out: list[RegressionResult] = []
        for row in results:
            sample_id, actual_intent, actual_entities, actual_response, actual_tool_calls = row
            sample = self._dataset.get_by_id(sample_id)
            if sample is None:
                out.append(RegressionResult(
                    sample_id=sample_id,
                    passed=False,
                    intent_match=False,
                    entities_match=False,
                    response_contains_match=False,
                    tool_calls_match=False,
                    errors=[f"Sample '{sample_id}' not found in dataset"],
                ))
                continue
            result = await self.run_single(
                sample, actual_intent, actual_entities, actual_response, actual_tool_calls,
            )
            out.append(result)
        return out

    def generate_report(self, results: list[RegressionResult]) -> dict[str, Any]:
        """Produce summary statistics from regression results."""
        total = len(results)
        if total == 0:
            return {
                "total": 0, "passed": 0, "failed": 0,
                "pass_rate": 0.0, "intent_accuracy": 0.0,
                "by_scenario": {},
            }

        passed = sum(1 for r in results if r.passed)
        intent_ok = sum(1 for r in results if r.intent_match)

        report: dict[str, Any] = {
            "total": total,
            "passed": passed,
            "failed": total - passed,
            "pass_rate": round(passed / total, 4),
            "intent_accuracy": round(intent_ok / total, 4),
        }

        # Consumers needing per-scenario breakdown should join with the
        # dataset. We provide an overall summary under "all".
        report["by_scenario"] = {
            "all": {
                "total": total,
                "passed": passed,
                "failed": total - passed,
                "pass_rate": round(passed / total, 4),
            }
        }
        return report


def _entities_match(expected: dict[str, Any], actual: dict[str, Any]) -> bool:
    """Check that every expected key-value pair is present in actual."""
    for key, value in expected.items():
        if key not in actual:
            return False
        if actual[key] != value:
            return False
    return True
