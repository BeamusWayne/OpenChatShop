"""Database-backed ContextManager using SQLModel.

Persists SessionContext to the database via ConversationLog entries.
Supports session recovery across restarts.
"""
from __future__ import annotations

import json
import logging
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from open_chat_shop.core.context import ContextManager
from open_chat_shop.core.types import (
    AgentMessage,
    Message,
    SessionContext,
    SessionMode,
    TokenBudget,
)
from open_chat_shop.core.exceptions import ContextError
from open_chat_shop.storage.models import ConversationLog
from open_chat_shop.storage.database import get_engine, create_tables, get_session

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

    async def load(self, session_id: str, channel: str = "web") -> SessionContext:
        """Load session from database or create a new one."""
        with get_session(self._engine) as session:
            from sqlmodel import select

            meta_entry = session.exec(
                select(ConversationLog).where(
                    ConversationLog.session_id == session_id,
                    ConversationLog.role == "__session_meta__",
                )
            ).first()

            if meta_entry:
                meta = json.loads(meta_entry.content)
                created_at = datetime.fromisoformat(meta["created_at"])
                last_active_at = datetime.fromisoformat(meta["last_active_at"])
            else:
                meta = {}
                created_at = datetime.now(timezone.utc)
                last_active_at = created_at

            logs = session.exec(
                select(ConversationLog)
                .where(
                    ConversationLog.session_id == session_id,
                    ConversationLog.role != "__session_meta__",
                )
                .order_by(ConversationLog.created_at)
            ).all()

            history = [
                Message(
                    role=log.role,
                    content=log.content,
                    timestamp=log.created_at,
                )
                for log in logs
            ]
            token_usage = sum(log.tokens_used for log in logs)

        return SessionContext(
            session_id=session_id,
            user_id=meta.get("user_id"),
            channel=meta.get("channel", "web"),
            history=history,
            summary=meta.get("summary"),
            slots=meta.get("slots", {}),
            fsm_state=meta.get("fsm_state", "idle"),
            current_scenario=meta.get("current_scenario"),
            token_usage=token_usage,
            user_role=meta.get("user_role", "customer"),
            created_at=created_at,
            last_active_at=last_active_at,
            mode=SessionMode(meta.get("mode", SessionMode.AI_MODE.value)),
            human_agent_id=meta.get("human_agent_id"),
        )

    async def save(self, context: SessionContext, response: AgentMessage) -> None:
        """Save context to database: upsert session metadata and assistant response."""
        try:
            with get_session(self._engine) as db:
                from sqlmodel import select

                # Upsert session metadata
                existing_meta = db.exec(
                    select(ConversationLog).where(
                        ConversationLog.session_id == context.session_id,
                        ConversationLog.role == "__session_meta__",
                    )
                ).first()

                meta_json = json.dumps(
                    {
                        "user_id": context.user_id,
                        "channel": context.channel,
                        "summary": context.summary,
                        "slots": context.slots,
                        "fsm_state": context.fsm_state,
                        "current_scenario": context.current_scenario,
                        "user_role": context.user_role,
                        "created_at": context.created_at.isoformat(),
                        "last_active_at": datetime.now(timezone.utc).isoformat(),
                        "mode": context.mode.value,
                        "human_agent_id": context.human_agent_id,
                    },
                    ensure_ascii=False,
                )

                if existing_meta:
                    existing_meta.content = meta_json
                    db.add(existing_meta)
                else:
                    db.add(
                        ConversationLog(
                            session_id=context.session_id,
                            user_id=context.user_id,
                            role="__session_meta__",
                            content=meta_json,
                        )
                    )

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

        return replace(
            context,
            history=kept,
            summary=new_summary,
            last_active_at=datetime.now(timezone.utc),
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
        return replace(context, slots=merged_slots)
