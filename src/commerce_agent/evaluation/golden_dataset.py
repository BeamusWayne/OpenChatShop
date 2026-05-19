"""Golden dataset for evaluation — structured test samples."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


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


_VALID_RISK_LEVELS = {"low", "medium", "high"}
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

    def load_from_dict(self, data: list[dict]) -> None:
        self._load_list(data)

    def get_by_intent(self, intent: str) -> list[GoldenSample]:
        return [s for s in self._samples if s.expected_intent == intent]

    def get_by_scenario(self, scenario: str) -> list[GoldenSample]:
        return [s for s in self._samples if s.scenario == scenario]

    def get_by_risk_level(self, level: str) -> list[GoldenSample]:
        return [s for s in self._samples if s.risk_level == level]

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

            if sample.sample_id in seen_ids:
                errors.append(
                    f"Duplicate sample_id: {sample.sample_id}"
                )
            seen_ids.add(sample.sample_id)

        return errors

    # -- internal helpers ---------------------------------------------------

    def _load_list(self, data: list[dict]) -> None:
        for item in data:
            self.add_sample(GoldenSample(**item))
