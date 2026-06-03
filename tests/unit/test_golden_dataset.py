"""Tests for built-in golden dataset — structure, coverage, filtering."""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

import open_chat_shop.evaluation.golden_dataset as gd
from open_chat_shop.evaluation.golden_dataset import (
    BUILT_IN_SAMPLES,
    GoldenSample,
    get_golden_dataset,
)

# The full curated dataset; the count is asserted explicitly so that a silent
# loss of samples during the JSON migration (or any future edit) fails loudly
# rather than degrading evaluation coverage unnoticed.
EXPECTED_SAMPLE_COUNT = 500

ALL_INTENTS = {
    "query_order",
    "query_logistics",
    "search_product",
    "check_refund_eligibility",
    "create_refund",
    "cancel_order",
    "modify_address",
    "handoff_to_human",
    "greeting",
    "thanks",
}

ALL_SCENARIO_TYPES = {"normal", "edge", "attack"}


@pytest.fixture
def dataset() -> list[GoldenSample]:
    return BUILT_IN_SAMPLES


# ---------------------------------------------------------------------------
# Structure and size
# ---------------------------------------------------------------------------


class TestGoldenDatasetStructure:
    """Verify dataset size and per-sample structure."""

    @pytest.mark.unit
    def test_dataset_has_50_plus_samples(self, dataset: list[GoldenSample]) -> None:
        assert len(dataset) >= 50

    @pytest.mark.unit
    def test_all_10_intents_covered(self, dataset: list[GoldenSample]) -> None:
        intents = {s.expected_intent for s in dataset}
        assert intents >= ALL_INTENTS, (
            f"Missing intents: {ALL_INTENTS - intents}"
        )

    @pytest.mark.unit
    def test_all_3_scenario_types_covered(self, dataset: list[GoldenSample]) -> None:
        types = {s.scenario_type for s in dataset}
        assert types >= ALL_SCENARIO_TYPES, (
            f"Missing scenario types: {ALL_SCENARIO_TYPES - types}"
        )

    @pytest.mark.unit
    def test_each_intent_has_at_least_5_samples(
        self, dataset: list[GoldenSample]
    ) -> None:
        counts: dict[str, int] = {}
        for s in dataset:
            counts[s.expected_intent] = counts.get(s.expected_intent, 0) + 1
        for intent in ALL_INTENTS:
            assert counts.get(intent, 0) >= 5, (
                f"Intent '{intent}' has only {counts.get(intent, 0)} samples (need >= 5)"
            )

    @pytest.mark.unit
    def test_sample_structure_completeness(self, dataset: list[GoldenSample]) -> None:
        for sample in dataset:
            assert isinstance(sample.sample_id, str) and sample.sample_id != ""
            assert isinstance(sample.scenario, str) and sample.scenario != ""
            assert isinstance(sample.intent, str) and sample.intent != ""
            assert isinstance(sample.expected_intent, str) and sample.expected_intent != ""
            assert isinstance(sample.expected_response_contains, list)
            assert isinstance(sample.expected_tool_calls, list)
            assert len(sample.expected_tool_calls) > 0
            assert sample.risk_level in {"low", "medium", "high"}
            assert sample.scenario_type in {"normal", "edge", "attack"}


# ---------------------------------------------------------------------------
# Uniqueness
# ---------------------------------------------------------------------------


class TestGoldenDatasetUniqueness:
    """Verify no duplicate IDs or duplicate inputs."""

    @pytest.mark.unit
    def test_no_duplicate_sample_ids(self, dataset: list[GoldenSample]) -> None:
        ids = [s.sample_id for s in dataset]
        assert len(ids) == len(set(ids)), f"Duplicate IDs: {_find_dupes(ids)}"

    @pytest.mark.unit
    def test_no_duplicate_inputs(self, dataset: list[GoldenSample]) -> None:
        inputs = [s.user_input for s in dataset]
        dupes = _find_dupes(inputs)
        assert len(inputs) == len(set(inputs)), (
            f"Duplicate user_input values: {dupes}"
        )


# ---------------------------------------------------------------------------
# Filtering via GoldenDataset
# ---------------------------------------------------------------------------


class TestGoldenDatasetFiltering:
    """Verify get_by_intent, get_by_scenario_type, and get_golden_dataset."""

    @pytest.mark.unit
    def test_get_by_intent_returns_correct_samples(self) -> None:
        ds = get_golden_dataset()
        results = ds.get_by_intent("search_product")
        assert len(results) >= 40
        assert all(s.expected_intent == "search_product" for s in results)

    @pytest.mark.unit
    def test_get_by_intent_returns_empty_for_unknown(self) -> None:
        ds = get_golden_dataset()
        results = ds.get_by_intent("nonexistent_intent")
        assert results == []

    @pytest.mark.unit
    def test_get_by_scenario_type_normal(self) -> None:
        ds = get_golden_dataset()
        results = ds.get_by_scenario_type("normal")
        assert len(results) >= 400
        assert all(s.scenario_type == "normal" for s in results)

    @pytest.mark.unit
    def test_get_by_scenario_type_edge(self) -> None:
        ds = get_golden_dataset()
        results = ds.get_by_scenario_type("edge")
        assert len(results) >= 5
        assert all(s.scenario_type == "edge" for s in results)

    @pytest.mark.unit
    def test_get_by_scenario_type_attack(self) -> None:
        ds = get_golden_dataset()
        results = ds.get_by_scenario_type("attack")
        assert len(results) >= 8
        assert all(s.scenario_type == "attack" for s in results)

    @pytest.mark.unit
    def test_get_golden_dataset_returns_valid(self) -> None:
        ds = get_golden_dataset()
        errors = ds.validate()
        assert errors == [], f"Validation errors: {errors}"

    @pytest.mark.unit
    def test_get_golden_dataset_len_matches_built_in(self) -> None:
        ds = get_golden_dataset()
        assert len(ds) == len(BUILT_IN_SAMPLES)

    @pytest.mark.unit
    def test_attack_samples_have_high_risk(self, dataset: list[GoldenSample]) -> None:
        for s in dataset:
            if s.scenario_type == "attack":
                assert s.risk_level == "high", (
                    f"Attack sample {s.sample_id} should have risk_level='high'"
                )


# ---------------------------------------------------------------------------
# JSON-backed loading (data lives in data/built_in_samples.json)
# ---------------------------------------------------------------------------


class TestGoldenDatasetJsonBacking:
    """Samples are loaded from JSON; loading must be lossless and faithful."""

    @pytest.mark.unit
    def test_loaded_sample_count_matches_expected_total(
        self, dataset: list[GoldenSample]
    ) -> None:
        assert len(dataset) == EXPECTED_SAMPLE_COUNT

    @pytest.mark.unit
    def test_json_file_record_count_matches_loaded_samples(
        self, dataset: list[GoldenSample]
    ) -> None:
        raw = gd._DATA_FILE.read_text(encoding="utf-8")
        records = json.loads(raw)
        assert len(records) == EXPECTED_SAMPLE_COUNT
        assert len(records) == len(dataset)

    @pytest.mark.unit
    def test_sample_fields_equivalent_to_json_source(
        self, dataset: list[GoldenSample]
    ) -> None:
        """Spot-check a sample (incl. an attack sample) is reconstructed
        field-for-field from the JSON, so expected/annotation values are not
        silently altered by the migration."""
        raw = gd._DATA_FILE.read_text(encoding="utf-8")
        records = {r["sample_id"]: r for r in json.loads(raw)}
        by_id = {s.sample_id: s for s in dataset}

        for sample_id in ("BO-001", "AT-007"):
            json_record = records[sample_id]
            loaded = dataclasses.asdict(by_id[sample_id])
            assert loaded == json_record, (
                f"Sample {sample_id} differs between JSON and loaded object"
            )

        # The attack sample's expected payload must survive verbatim.
        assert records["AT-007"]["expected_entities"] == {
            "address": "../../../etc/passwd"
        }
        assert records["AT-007"]["scenario_type"] == "attack"
        assert records["AT-007"]["risk_level"] == "high"

    @pytest.mark.unit
    def test_json_stored_with_literal_chinese(self) -> None:
        """ensure_ascii=False keeps Chinese text human-readable in the data
        file; a regression to escaped \\uXXXX would still parse but signals the
        wrong serialization style."""
        raw = Path(gd._DATA_FILE).read_text(encoding="utf-8")
        assert "退款" in raw
        assert "\\u9000" not in raw  # escaped form of 退


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_dupes(items: list[str]) -> list[str]:
    """Return items that appear more than once."""
    seen: set[str] = set()
    dupes: set[str] = set()
    for item in items:
        if item in seen:
            dupes.add(item)
        seen.add(item)
    return sorted(dupes)
