"""Order Inquiry scenario FSM.

Flow: idle -> querying -> located -> displaying -> follow_up -> completed
                                                       |-> cancelled
"""
from __future__ import annotations

from typing import ClassVar

from open_chat_shop.core.scenario import ScenarioFSM
from open_chat_shop.core.types import SessionContext, Transition


class OrderInquiryScenarioFSM(ScenarioFSM):
    """Order inquiry: user wants to check order status, logistics, etc.

    States:
      idle       -- initial, awaiting order identification
      querying   -- system is searching for the order
      located    -- order found, ready to display details
      displaying -- order details shown to user
      follow_up  -- user has follow-up questions about the order
      completed  -- inquiry resolved
      cancelled  -- user cancelled or timed out
    """

    name = "order_inquiry"
    states: ClassVar[list[str]] = [
        "idle", "querying", "located", "displaying",
        "follow_up", "completed", "cancelled",
    ]
    timeout_seconds = 180

    def __init__(self) -> None:
        self.transitions: list[Transition] = [
            Transition(from_state="idle", to_state="querying", trigger="start_query"),
            Transition(from_state="idle", to_state="cancelled", trigger="cancel"),
            Transition(
                from_state="querying", to_state="located", trigger="order_found",
                guard=self._has_order_id,
            ),
            Transition(from_state="querying", to_state="cancelled", trigger="not_found"),
            Transition(from_state="located", to_state="displaying", trigger="display"),
            Transition(from_state="displaying", to_state="follow_up", trigger="ask_followup"),
            Transition(from_state="displaying", to_state="completed", trigger="resolve"),
            Transition(from_state="follow_up", to_state="completed", trigger="resolve"),
            Transition(from_state="follow_up", to_state="cancelled", trigger="cancel"),
            Transition(from_state="displaying", to_state="cancelled", trigger="cancel"),
            Transition(from_state="located", to_state="cancelled", trigger="cancel"),
        ]

    def get_initial_state(self) -> str:
        return "idle"

    def get_allowed_transitions(self, current_state: str) -> list[Transition]:
        return [t for t in self.transitions if t.from_state == current_state]

    @staticmethod
    def _has_order_id(context: SessionContext) -> bool:
        return bool(context.slots.get("order_id"))
