"""Golden dataset for evaluation — structured test samples."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class GoldenSample:
    """A single annotated test sample for regression evaluation."""

    sample_id: str
    scenario: str
    intent: str
    user_input: str
    expected_intent: str
    expected_entities: dict[str, object]
    expected_response_contains: list[str]
    expected_tool_calls: list[str]
    risk_level: str = "low"
    scenario_type: str = "normal"  # normal | edge | attack


_VALID_RISK_LEVELS = {"low", "medium", "high"}
_VALID_SCENARIO_TYPES = {"normal", "edge", "attack"}
_REQUIRED_FIELDS = (
    "sample_id",
    "scenario",
    "intent",
    "user_input",
    "expected_intent",
    "expected_entities",
    "expected_response_contains",
    "expected_tool_calls",
)


class GoldenDataset:
    """Collection of golden samples with loading and filtering."""

    def __init__(self) -> None:
        self._samples: list[GoldenSample] = []

    def add_sample(self, sample: GoldenSample) -> None:
        self._samples.append(sample)

    def load_from_json(self, path: str) -> None:
        raw = Path(path).read_text(encoding="utf-8")
        data = json.loads(raw)
        self._load_list(data)

    def load_from_dict(self, data: list[dict[str, Any]]) -> None:
        self._load_list(data)

    def get_by_intent(self, intent: str) -> list[GoldenSample]:
        return [s for s in self._samples if s.expected_intent == intent]

    def get_by_scenario(self, scenario: str) -> list[GoldenSample]:
        return [s for s in self._samples if s.scenario == scenario]

    def get_by_risk_level(self, level: str) -> list[GoldenSample]:
        return [s for s in self._samples if s.risk_level == level]

    def get_by_scenario_type(self, scenario_type: str) -> list[GoldenSample]:
        return [s for s in self._samples if s.scenario_type == scenario_type]

    def get_by_id(self, sample_id: str) -> GoldenSample | None:
        for s in self._samples:
            if s.sample_id == sample_id:
                return s
        return None

    def __len__(self) -> int:
        return len(self._samples)

    def validate(self) -> list[str]:
        """Return a list of validation error strings. Empty means valid."""
        errors: list[str] = []
        seen_ids: set[str] = set()

        for sample in self._samples:
            for attr in _REQUIRED_FIELDS:
                val = getattr(sample, attr, None)
                if val is None or val == "" or val == []:
                    errors.append(
                        f"Sample {sample.sample_id}: empty or missing '{attr}'"
                    )

            if sample.risk_level not in _VALID_RISK_LEVELS:
                errors.append(
                    f"Sample {sample.sample_id}: invalid risk_level "
                    f"'{sample.risk_level}', must be one of {_VALID_RISK_LEVELS}"
                )

            if sample.scenario_type not in _VALID_SCENARIO_TYPES:
                errors.append(
                    f"Sample {sample.sample_id}: invalid scenario_type "
                    f"'{sample.scenario_type}', must be one of {_VALID_SCENARIO_TYPES}"
                )

            if sample.sample_id in seen_ids:
                errors.append(
                    f"Duplicate sample_id: {sample.sample_id}"
                )
            seen_ids.add(sample.sample_id)

        return errors

    # -- internal helpers ---------------------------------------------------

    def _load_list(self, data: list[dict[str, Any]]) -> None:
        for item in data:
            self.add_sample(GoldenSample(**item))


# ---------------------------------------------------------------------------
# Built-in golden samples (500 samples covering all 10 intents)
# ---------------------------------------------------------------------------
# Intents: query_order, query_logistics, search_product,
#          check_refund_eligibility, create_refund, cancel_order,
#          modify_address, handoff_to_human, greeting, thanks
#
# The sample data lives in data/built_in_samples.json (UTF-8, ensure_ascii
# disabled so Chinese text is stored literally). Keeping it as data instead of
# an inline Python literal keeps this module under the project size limit and
# lets the dataset be edited without touching code.

_DATA_FILE = Path(__file__).parent / "data" / "built_in_samples.json"


def _load_built_in_samples() -> list[GoldenSample]:
    """Load the built-in golden samples from the bundled JSON data file."""
    raw = _DATA_FILE.read_text(encoding="utf-8")
    data = json.loads(raw)
    return [GoldenSample(**item) for item in data]


BUILT_IN_SAMPLES: list[GoldenSample] = _load_built_in_samples()


def get_golden_dataset() -> GoldenDataset:
    """Return a GoldenDataset pre-loaded with all built-in samples."""
    ds = GoldenDataset()
    for sample in BUILT_IN_SAMPLES:
        ds.add_sample(sample)
    return ds
