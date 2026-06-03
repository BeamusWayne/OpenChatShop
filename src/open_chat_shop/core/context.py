"""Context manager for session state, history, and token budgets.

Implements contracts.md S8: ContextManager ABC and InMemoryContextManager.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from datetime import UTC, datetime

from open_chat_shop.core.types import (
    AgentMessage,
    SessionContext,
    SessionMode,
    TokenBudget,
)

logger = logging.getLogger(__name__)


class ContextManager(ABC):
    """Abstract interface for session context management."""

    @abstractmethod
    async def load(self, session_id: str, channel: str = "web") -> SessionContext:
        """Load an existing session or create a new one."""
        ...

    @abstractmethod
    async def save(self, context: SessionContext, response: AgentMessage) -> None:
        """Persist updated context after generating a response."""
        ...

    @abstractmethod
    async def compress(self, context: SessionContext) -> SessionContext:
        """Compress history when it exceeds the token budget."""
        ...

    @abstractmethod
    def get_token_budget(self, context: SessionContext) -> TokenBudget:
        """Calculate the token budget allocation for the current context."""
        ...

    @abstractmethod
    async def update_slots(self, context: SessionContext, new_entities: dict) -> SessionContext:
        """Merge new slot entities into the context."""
        ...


class InMemoryContextManager(ContextManager):
    """In-memory implementation for testing and development."""

    def __init__(
        self,
        max_history_tokens: int = 2048,
        max_context_tokens: int = 4096,
        ttl_seconds: float = 1800.0,
    ) -> None:
        self._sessions: dict[str, SessionContext] = {}
        self._expiry: dict[str, float] = {}
        self._max_history_tokens = max_history_tokens
        self._max_context_tokens = max_context_tokens
        self._ttl_seconds = ttl_seconds

    def _evict_expired(self) -> None:
        """Remove sessions whose TTL has elapsed."""
        now = time.monotonic()
        expired = [sid for sid, deadline in self._expiry.items() if now > deadline]
        for sid in expired:
            self._sessions.pop(sid, None)
            del self._expiry[sid]

    async def load(self, session_id: str, channel: str = "web") -> SessionContext:
        """Load or create a session context."""
        self._evict_expired()
        if session_id not in self._sessions:
            now = datetime.now(UTC)
            self._sessions[session_id] = SessionContext(
                session_id=session_id,
                user_id=None,
                channel=channel,
                history=[],
                summary=None,
                slots={},
                fsm_state="idle",
                current_scenario=None,
                token_usage=0,
                user_role="customer",
                created_at=now,
                last_active_at=now,
                mode=SessionMode.AI_MODE,
                human_agent_id=None,
            )
        self._expiry[session_id] = time.monotonic() + self._ttl_seconds
        return self._sessions[session_id]

    async def save(self, context: SessionContext, response: AgentMessage) -> None:
        """Save updated context. Updates last_active_at timestamp."""
        self._evict_expired()
        updated = SessionContext(
            session_id=context.session_id,
            user_id=context.user_id,
            channel=context.channel,
            history=[*context.history],
            summary=context.summary,
            slots=context.slots,
            fsm_state=context.fsm_state,
            current_scenario=context.current_scenario,
            token_usage=context.token_usage,
            user_role=context.user_role,
            created_at=context.created_at,
            last_active_at=datetime.now(UTC),
            mode=context.mode,
            human_agent_id=context.human_agent_id,
        )
        self._sessions[context.session_id] = updated
        self._expiry[context.session_id] = time.monotonic() + self._ttl_seconds

    async def compress(self, context: SessionContext) -> SessionContext:
        """Compress history when it exceeds the token budget.

        Simple sliding window: keep the last 20% of messages (min 4),
        and append a summary prefix for the dropped messages.
        """
        budget = self.get_token_budget(context)
        if not budget.needs_compression:
            return context

        total = len(context.history)
        keep_count = max(4, total // 5)
        dropped = context.history[:-keep_count]
        kept = context.history[-keep_count:]

        # Generate a simple summary prefix.
        # In production, this would call an LLM to summarise the dropped messages.
        summary_prefix = f"[Previously compressed {len(dropped)} messages] "
        new_summary = (context.summary or "") + summary_prefix

        return SessionContext(
            session_id=context.session_id,
            user_id=context.user_id,
            channel=context.channel,
            history=kept,
            summary=new_summary,
            slots=context.slots,
            fsm_state=context.fsm_state,
            current_scenario=context.current_scenario,
            token_usage=context.token_usage,
            user_role=context.user_role,
            created_at=context.created_at,
            last_active_at=datetime.now(UTC),
            mode=context.mode,
            human_agent_id=context.human_agent_id,
        )

    def get_token_budget(self, context: SessionContext) -> TokenBudget:
        """Calculate token budget: 20% system, 50% history, 20% tools, 10% slots."""
        total = self._max_context_tokens
        # Rough estimate: 4 characters per token.
        history_tokens = sum(
            len(m.content) // 4 for m in context.history if m.content
        )

        return TokenBudget(
            total=total,
            system_prompt=int(total * 0.2),
            history=int(total * 0.5),
            tool_results=int(total * 0.2),
            slot_entities=int(total * 0.1),
            history_used=history_tokens,
            needs_compression=history_tokens > int(total * 0.5),
        )

    async def update_slots(
        self, context: SessionContext, new_entities: dict
    ) -> SessionContext:
        """Merge new entities into existing slots. Returns a new SessionContext."""
        merged_slots = {**context.slots, **new_entities}
        return SessionContext(
            session_id=context.session_id,
            user_id=context.user_id,
            channel=context.channel,
            history=context.history,
            summary=context.summary,
            slots=merged_slots,
            fsm_state=context.fsm_state,
            current_scenario=context.current_scenario,
            token_usage=context.token_usage,
            user_role=context.user_role,
            created_at=context.created_at,
            last_active_at=context.last_active_at,
            mode=context.mode,
            human_agent_id=context.human_agent_id,
        )

    def get(self, session_id: str) -> SessionContext | None:
        """Synchronous lookup for session context (used by API guards)."""
        return self._sessions.get(session_id)
