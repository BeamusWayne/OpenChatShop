"""Tests for SlotTracker — entity tracking across dialogue turns."""
from __future__ import annotations

import pytest

from open_chat_shop.core.slot_tracker import (
    SlotDefinition,
    SlotTracker,
    SlotStatus,
    create_builtin_tracker,
    BUILTIN_SCENARIOS,
)


class TestSlotDefinition:
    @pytest.mark.unit
    def test_defaults(self):
        slot = SlotDefinition(name="test", type="string")
        assert slot.required is True
        assert slot.prompt == ""
        assert slot.enum_values == []


class TestSlotTracker:
    @pytest.mark.unit
    def test_register_and_check_empty(self):
        tracker = SlotTracker()
        tracker.register_scenario("test", [
            SlotDefinition(name="a", type="string", required=True, prompt="Enter a"),
        ])
        status = tracker.get_status("test", {})
        assert status.missing == ["a"]
        assert not status.complete

    @pytest.mark.unit
    def test_all_required_filled(self):
        tracker = SlotTracker()
        tracker.register_scenario("test", [
            SlotDefinition(name="a", type="string", required=True),
            SlotDefinition(name="b", type="string", required=True),
        ])
        status = tracker.get_status("test", {"a": "val_a", "b": "val_b"})
        assert status.complete
        assert status.missing == []

    @pytest.mark.unit
    def test_optional_not_required(self):
        tracker = SlotTracker()
        tracker.register_scenario("test", [
            SlotDefinition(name="a", type="string", required=True),
            SlotDefinition(name="b", type="string", required=False),
        ])
        status = tracker.get_status("test", {"a": "val_a"})
        assert status.complete

    @pytest.mark.unit
    def test_partial_fill(self):
        tracker = SlotTracker()
        tracker.register_scenario("test", [
            SlotDefinition(name="a", type="string", required=True),
            SlotDefinition(name="b", type="string", required=True),
        ])
        status = tracker.get_status("test", {"a": "val_a"})
        assert not status.complete
        assert "b" in status.missing

    @pytest.mark.unit
    def test_unknown_scenario_auto_complete(self):
        tracker = SlotTracker()
        status = tracker.get_status("unknown", {})
        assert status.complete

    @pytest.mark.unit
    def test_merge_slots(self):
        tracker = SlotTracker()
        result = tracker.merge_slots({"a": "1"}, {"b": "2"})
        assert result == {"a": "1", "b": "2"}

    @pytest.mark.unit
    def test_merge_overwrites(self):
        tracker = SlotTracker()
        result = tracker.merge_slots({"a": "old"}, {"a": "new"})
        assert result == {"a": "new"}

    @pytest.mark.unit
    def test_merge_does_not_mutate(self):
        tracker = SlotTracker()
        original = {"a": "1"}
        tracker.merge_slots(original, {"b": "2"})
        assert original == {"a": "1"}

    @pytest.mark.unit
    def test_missing_prompt_with_registered_prompt(self):
        tracker = SlotTracker()
        tracker.register_scenario("test", [
            SlotDefinition(name="order_id", type="string", required=True,
                           prompt="请问您的订单号是多少？"),
        ])
        prompt = tracker.get_missing_prompt("test", ["order_id"])
        assert "订单号" in prompt

    @pytest.mark.unit
    def test_missing_prompt_no_registered(self):
        tracker = SlotTracker()
        prompt = tracker.get_missing_prompt("test", ["field1"])
        assert "field1" in prompt

    @pytest.mark.unit
    def test_missing_prompt_empty_list(self):
        tracker = SlotTracker()
        prompt = tracker.get_missing_prompt("test", [])
        assert prompt == ""

    @pytest.mark.unit
    def test_validate_string_slot(self):
        tracker = SlotTracker()
        tracker.register_scenario("test", [
            SlotDefinition(name="s", type="string", required=True),
        ])
        status = tracker.get_status("test", {"s": "valid"})
        assert "s" in status.filled
        status_empty = tracker.get_status("test", {"s": ""})
        assert "s" in status_empty.missing

    @pytest.mark.unit
    def test_validate_number_slot(self):
        tracker = SlotTracker()
        tracker.register_scenario("test", [
            SlotDefinition(name="n", type="number", required=True),
        ])
        status_ok = tracker.get_status("test", {"n": 42})
        assert "n" in status_ok.filled
        status_bad = tracker.get_status("test", {"n": "not_a_number"})
        assert "n" in status_bad.missing

    @pytest.mark.unit
    def test_validate_enum_slot(self):
        tracker = SlotTracker()
        tracker.register_scenario("test", [
            SlotDefinition(name="e", type="enum", required=True,
                           enum_values=["a", "b", "c"]),
        ])
        status_ok = tracker.get_status("test", {"e": "a"})
        assert "e" in status_ok.filled
        status_bad = tracker.get_status("test", {"e": "invalid"})
        assert "e" in status_bad.missing

    @pytest.mark.unit
    def test_validate_boolean_slot(self):
        tracker = SlotTracker()
        tracker.register_scenario("test", [
            SlotDefinition(name="b", type="boolean", required=True),
        ])
        status_ok = tracker.get_status("test", {"b": True})
        assert "b" in status_ok.filled
        status_bad = tracker.get_status("test", {"b": "yes"})
        assert "b" in status_bad.missing


class TestBuiltinTracker:
    @pytest.mark.unit
    def test_query_order_requires_order_id(self):
        tracker = create_builtin_tracker()
        status = tracker.get_status("query_order", {})
        assert not status.complete
        assert "order_id" in status.missing

    @pytest.mark.unit
    def test_query_order_complete(self):
        tracker = create_builtin_tracker()
        status = tracker.get_status("query_order", {"order_id": "ORD-123"})
        assert status.complete

    @pytest.mark.unit
    def test_refund_requires_order_id_not_reason(self):
        tracker = create_builtin_tracker()
        status = tracker.get_status("request_refund", {"reason": "broken"})
        assert not status.complete
        assert "order_id" in status.missing

    @pytest.mark.unit
    def test_modify_address_requires_both(self):
        tracker = create_builtin_tracker()
        status = tracker.get_status("modify_address", {"order_id": "ORD-1"})
        assert not status.complete
        assert "new_address" in status.missing

    @pytest.mark.unit
    def test_complaint_category_prompt(self):
        tracker = create_builtin_tracker()
        prompt = tracker.get_missing_prompt("complaint", ["complaint_category"])
        assert "投诉" in prompt or "category" in prompt.lower() or "方面" in prompt
