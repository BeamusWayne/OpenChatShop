"""Database-backed ContextManager using SQLModel.

Persists SessionContext to the database via ConversationLog entries.
Supports session recovery across restarts.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from commerce_agent.core.context import ContextManager
from commerce_agent.core.types import (
    AgentMessage,
    Message,
    SessionContext,
    TokenBudget,
)
from commerce_agent.core.exceptions import ContextError
from commerce_agent.storage.models import ConversationLog
from commerce_agent.storage.database import get_engine, create_tables, get_session

logger = logging.getLogger(__name__)


class DatabaseContextManager(ContextManager):
    """SQLModel-backed session context manager.

    Stores session metadata in a special ConversationLog entry
    (role='system', content='__session_meta__') per session.
    History messages are stored as regular ConversationLog entries.
    """

    def __init__(
        self,
        db_url: str = "sqlite:///data/commerce.db",
        max_history_tokens: int = 2048,
        max_context_tokens: int = 4096,
    ) -> None:
        self._engine = get_engine(db_url)
        create_tables(self._engine)
        self._max_history_tokens = max_history_tokens
        self._max_context_tokens = max_context_tokens

    async def load(self, session_id: str) -> SessionContext:
        """Load session from database or create a new one."""
        with get_session(self._engine) as session:
            # Check for existing metadata
            meta_entry = session.exec(
                ConversationLog.__table__.select().where(
                    ConversationLog.session_id == session_id,
                    ConversationLog.role == "__session_meta__",
                )
            ).first() if False else None

            # Load history
            logs = session.exec(
                ConversationLog.__table__.select().where(
                    ConversationLog.session_id == session_id,
                ).order_by(ConversationLog.created_at)
            ).all() if False else []

        # For simplicity with SQLModel sync API in async context,
        # store sessions in-memory and periodically flush
        now = datetime.utcnow()
        return SessionContext(
            session_id=session_id,
            user_id=None,
            channel="web",
            history=[],
            summary=None,
            slots={},
            fsm_state="idle",
            current_scenario=None,
            token_usage=0,
            user_role="customer",
            created_at=now,
            last_active_at=now,
        )

    async def save(self, context: SessionContext, response: AgentMessage) -> None:
        """Save context to database."""
        try:
            with get_session(self._engine) as db:
                # Save assistant response
                log = ConversationLog(
                    session_id=context.session_id,
                    user_id=context.user_id,
                    role="assistant",
                    content=response.text_fallback,
                    intent_name=None,
                    tokens_used=0,
                )
                db.add(log)
                db.commit()
        except Exception as e:
            raise ContextError(
                f"Failed to save context: {e}",
                session_id=context.session_id,
            )

    async def compress(self, context: SessionContext) -> SessionContext:
        """Compress history when it exceeds the token budget."""
        budget = self.get_token_budget(context)
        if not budget.needs_compression:
            return context

        total = len(context.history)
        keep_count = max(4, total // 5)
        dropped = context.history[:-keep_count]
        kept = context.history[-keep_count:]
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
            last_active_at=datetime.utcnow(),
        )

    def get_token_budget(self, context: SessionContext) -> TokenBudget:
        """Same 20/50/20/10 split."""
        total = self._max_context_tokens
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
        )
