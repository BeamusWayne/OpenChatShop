"""Slot Tracker — multi-turn entity accumulation for dialogue.

Implements contracts.md §1.7: tracks entities across turns,
validates types, detects missing slots, and generates prompts
for missing information.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import logging

logger = logging.getLogger(__name__)


@dataclass
class SlotDefinition:
    """Schema for a single slot."""
    name: str
    type: str  # "string", "number", "boolean", "enum"
    required: bool = True
    prompt: str = ""  # What to ask when missing
    enum_values: list[str] = field(default_factory=list)
    validation_pattern: str = ""  # Regex pattern for string validation


@dataclass
class SlotStatus:
    """Current status of all tracked slots."""
    filled: dict[str, Any] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    total: int = 0
    complete: bool = False


class SlotTracker:
    """Track and validate entity slots across multiple dialogue turns.

    Accumulates entities from intent recognition results,
    validates against defined slot schemas, and reports
    what's still missing for the current scenario.
    """

    def __init__(self) -> None:
        self._schemas: dict[str, list[SlotDefinition]] = {}

    def register_scenario(self, scenario: str, slots: list[SlotDefinition]) -> None:
        """Register slot definitions for a scenario."""
        self._schemas[scenario] = slots

    def get_status(
        self,
        scenario: str,
        current_slots: dict[str, Any],
    ) -> SlotStatus:
        """Check slot filling status for a scenario.

        Compares current_slots against the registered schema
        and returns what's filled, what's missing, and whether
        all required slots are complete.
        """
        schema = self._schemas.get(scenario, [])
        if not schema:
            return SlotStatus(filled=current_slots, missing=[], total=0, complete=True)

        filled = {}
        missing: list[str] = []

        for slot_def in schema:
            if slot_def.name in current_slots:
                value = current_slots[slot_def.name]
                if self._validate_slot(slot_def, value):
                    filled[slot_def.name] = value
                else:
                    if slot_def.required:
                        missing.append(slot_def.name)
            elif slot_def.required:
                missing.append(slot_def.name)

        return SlotStatus(
            filled=filled,
            missing=missing,
            total=len(schema),
            complete=len(missing) == 0,
        )

    def merge_slots(
        self,
        existing: dict[str, Any],
        new_entities: dict[str, Any],
    ) -> dict[str, Any]:
        """Merge new entities into existing slots.

        New values overwrite existing ones. Returns a new dict
        (does not mutate existing).
        """
        return {**existing, **new_entities}

    def get_missing_prompt(self, scenario: str, missing: list[str]) -> str:
        """Generate a prompt asking for missing slot values.

        Uses the registered slot definitions to create
        a user-friendly prompt for the first missing slot.
        """
        schema = self._schemas.get(scenario, [])
        slot_map = {s.name: s for s in schema}

        for slot_name in missing:
            slot_def = slot_map.get(slot_name)
            if slot_def and slot_def.prompt:
                return slot_def.prompt

        if missing:
            return f"请提供以下信息：{', '.join(missing)}"
        return ""

    def _validate_slot(self, slot_def: SlotDefinition, value: Any) -> bool:
        """Validate a slot value against its definition."""
        if slot_def.type == "string":
            return isinstance(value, str) and len(value) > 0
        elif slot_def.type == "number":
            return isinstance(value, (int, float))
        elif slot_def.type == "boolean":
            return isinstance(value, bool)
        elif slot_def.type == "enum":
            return value in slot_def.enum_values
        return True


# Pre-defined slot schemas for built-in scenarios
BUILTIN_SCENARIOS: dict[str, list[SlotDefinition]] = {
    "query_order": [
        SlotDefinition(name="order_id", type="string", required=True,
                       prompt="请问您的订单号是多少？"),
    ],
    "create_refund": [
        SlotDefinition(name="order_id", type="string", required=True,
                       prompt="请问您要退款的订单号是多少？"),
        SlotDefinition(name="reason", type="string", required=False,
                       prompt="请问退款原因是什么？"),
    ],
    "cancel_order": [
        SlotDefinition(name="order_id", type="string", required=True,
                       prompt="请问您要取消的订单号是多少？"),
    ],
    "modify_address": [
        SlotDefinition(name="order_id", type="string", required=True,
                       prompt="请问您要修改地址的订单号是多少？"),
        SlotDefinition(name="new_address", type="string", required=True,
                       prompt="请问新的收货地址是什么？"),
    ],
    "search_product": [
        SlotDefinition(name="query", type="string", required=True,
                       prompt="请问您想搜索什么商品？"),
        SlotDefinition(name="category", type="enum", required=False,
                       enum_values=["electronics", "clothing", "food", "home", "other"]),
    ],
    "complaint": [
        SlotDefinition(name="complaint_category", type="enum", required=True,
                       prompt="请问您要投诉哪个方面？(quality/service/logistics/other)",
                       enum_values=["quality", "service", "logistics", "other"]),
        SlotDefinition(name="complaint_detail", type="string", required=False,
                       prompt="请详细描述您的问题。"),
    ],
}


def create_builtin_tracker() -> SlotTracker:
    """Create a SlotTracker pre-loaded with built-in scenario schemas."""
    tracker = SlotTracker()
    for scenario, slots in BUILTIN_SCENARIOS.items():
        tracker.register_scenario(scenario, slots)
    return tracker
