"""Complaint handling scenario FSM.

Flow: idle -> received -> classified -> investigating -> resolving -> resolved
                                                      |-> escalated
"""
from __future__ import annotations

from open_chat_shop.core.scenario import ScenarioFSM
from open_chat_shop.core.types import SessionContext, Transition


class ComplaintScenarioFSM(ScenarioFSM):
    """Complaint handling: user has a complaint about products or service.

    States:
      idle          -- initial, complaint not yet registered
      received      -- complaint text captured
      classified    -- complaint categorized (quality/service/logistics/other)
      investigating -- looking into the issue
      resolving     -- providing a solution
      resolved      -- complaint addressed
      escalated     -- escalated to human agent
    """

    name = "complaint"
    states = [
        "idle", "received", "classified", "investigating",
        "resolving", "resolved", "escalated",
    ]
    timeout_seconds = 600

    VALID_CATEGORIES = {"quality", "service", "logistics", "other"}

    def __init__(self) -> None:
        self.transitions: list[Transition] = [
            Transition(from_state="idle", to_state="received", trigger="submit"),
            Transition(
                from_state="received", to_state="classified", trigger="classify",
                guard=self._has_category,
            ),
            Transition(
                from_state="classified", to_state="investigating", trigger="investigate",
            ),
            Transition(
                from_state="investigating", to_state="resolving", trigger="resolve_start",
            ),
            Transition(from_state="resolving", to_state="resolved", trigger="complete"),
            Transition(
                from_state="investigating", to_state="escalated", trigger="escalate",
            ),
            Transition(
                from_state="resolving", to_state="escalated", trigger="escalate",
            ),
            Transition(
                from_state="classified", to_state="escalated", trigger="escalate",
            ),
        ]

    def get_initial_state(self) -> str:
        return "idle"

    def get_allowed_transitions(self, current_state: str) -> list[Transition]:
        return [t for t in self.transitions if t.from_state == current_state]

    @staticmethod
    def _has_category(context: SessionContext) -> bool:
        category = context.slots.get("complaint_category", "")
        return category in ComplaintScenarioFSM.VALID_CATEGORIES
