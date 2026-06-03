"""Scenario FSM framework for business dialogue flows.

Provides an abstract base class for building state-machine-driven
conversation scenarios (e.g. refund, exchange, complaint) and a concrete
RefundScenarioFSM implementation.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import ClassVar

from open_chat_shop.core.types import SessionContext, Transition

logger = logging.getLogger(__name__)


class ScenarioFSM(ABC):
    """Abstract base for a business-scenario state machine.

    Subclasses must define ``name``, ``states``, and implement
    ``get_initial_state`` and ``get_allowed_transitions``.
    """

    name: str
    states: ClassVar[list[str]]
    transitions: list[Transition]
    timeout_seconds: int = 300

    @abstractmethod
    def get_initial_state(self) -> str:
        """Return the initial state for this scenario."""

    @abstractmethod
    def get_allowed_transitions(self, current_state: str) -> list[Transition]:
        """Return transitions that originate from *current_state*."""

    def can_transition(
        self,
        current_state: str,
        trigger: str,
        context: SessionContext,
    ) -> bool:
        """Check whether *trigger* is a valid transition from *current_state*.

        Evaluates the guard (if any) against *context*.  Returns ``True``
        only when both trigger matches and the guard passes.
        """
        for t in self.get_allowed_transitions(current_state):
            if t.trigger == trigger and (t.guard is None or t.guard(context)):
                return True
        return False

    async def execute_transition(
        self,
        current_state: str,
        trigger: str,
        context: SessionContext,
    ) -> SessionContext:
        """Execute a state transition and return a **new** SessionContext.

        The original *context* is never mutated.  Raises ``ValueError``
        when the transition is not allowed.
        """
        if not self.can_transition(current_state, trigger, context):
            raise ValueError(
                f"Transition '{trigger}' not allowed from state '{current_state}' "
                f"in scenario '{self.name}'"
            )

        for t in self.get_allowed_transitions(current_state):
            if t.trigger == trigger:
                if t.action is not None:
                    new_context = await t.action(context)
                else:
                    new_context = context
                # Build a new immutable context with updated fsm_state
                return SessionContext(
                    session_id=new_context.session_id,
                    user_id=new_context.user_id,
                    channel=new_context.channel,
                    history=new_context.history,
                    summary=new_context.summary,
                    slots=new_context.slots,
                    fsm_state=t.to_state,
                    current_scenario=self.name,
                    token_usage=new_context.token_usage,
                    user_role=new_context.user_role,
                    created_at=new_context.created_at,
                    last_active_at=new_context.last_active_at,
                )
        # Should be unreachable because can_transition already validated
        raise ValueError(f"No matching transition for trigger '{trigger}'")


class RefundScenarioFSM(ScenarioFSM):
    """Refund scenario: initiated -> confirmed -> processing -> completed
                                                  \\-> cancelled

    Any state can transition to ``cancelled`` via the ``cancel`` trigger.
    """

    name = "refund"
    states: ClassVar[list[str]] = ["initiated", "confirmed", "processing", "completed", "cancelled"]
    timeout_seconds = 300

    def __init__(self) -> None:
        self.transitions: list[Transition] = [
            Transition(from_state="initiated", to_state="confirmed", trigger="confirm"),
            Transition(from_state="confirmed", to_state="processing", trigger="process"),
            Transition(from_state="processing", to_state="completed", trigger="complete"),
            Transition(from_state="processing", to_state="cancelled", trigger="cancel"),
            Transition(from_state="confirmed", to_state="cancelled", trigger="cancel"),
            Transition(from_state="initiated", to_state="cancelled", trigger="cancel"),
        ]

    def get_initial_state(self) -> str:
        return "initiated"

    def get_allowed_transitions(self, current_state: str) -> list[Transition]:
        return [t for t in self.transitions if t.from_state == current_state]
