"""Pending-slot recovery — multi-turn slot filling.

Extracted from :class:`DialogueOrchestrator`. When a previous turn left a
``clarify`` action with missing slots persisted on the context, this
collaborator attempts to fill them from the user's next reply and either
re-prompts (still missing) or executes the now-complete action. Holds a
back-reference to the orchestrator (``host``) for the shared execution
primitives (``_tool_injector``, ``_strategy``, ``_execute_action``).
"""
from __future__ import annotations

import re as _re
from typing import TYPE_CHECKING, Any

from open_chat_shop.core.intent import _extract_entities
from open_chat_shop.core.types import (
    Action,
    AgentMessage,
    Intent,
    SessionContext,
    UserMessage,
)

if TYPE_CHECKING:
    from open_chat_shop.core.orchestrator import DialogueOrchestrator


class PendingSlotResolver:
    """Fills pending missing slots from the user's follow-up reply."""

    def __init__(self, host: DialogueOrchestrator) -> None:
        self._host = host

    async def resolve(
        self,
        message: UserMessage,
        context: SessionContext,
        pending: dict[str, Any],
    ) -> AgentMessage | None:
        """Attempt to fill pending missing slots from the user's response.

        Returns a complete AgentMessage if all slots are now filled,
        or *None* if the user's input doesn't resolve the pending action
        and the normal intent-classification flow should proceed instead.
        """
        host = self._host
        pending_intent_name: str = pending.get("intent_name", "")
        missing_slots: list[str] = pending.get("missing_slots", [])
        tool_name: str | None = pending.get("tool_name")
        existing_params: dict[str, Any] = dict(pending.get("params", {}))

        # Extract entities using the intent-aware extractor
        entities: dict[str, Any] = _extract_entities(
            message.content, pending_intent_name,
        )

        # Specific slot extraction (regex-based)
        for slot in missing_slots:
            if slot in entities:
                continue
            if slot == "order_id":
                m = _re.search(r"ORD-[\w]+", message.content, _re.IGNORECASE)
                if m:
                    entities["order_id"] = m.group(0)

        # Generic fallback: only if no specific slot was filled above
        specific_filled = any(s in entities for s in ("order_id", "keyword"))
        if not specific_filled:
            for slot in missing_slots:
                if slot in entities:
                    continue
                if slot == "keyword":
                    entities["keyword"] = message.content.strip()
                elif slot == "reason":
                    entities["reason"] = message.content.strip()
                elif slot == "address":
                    entities["address"] = message.content.strip()
                break  # One generic slot per message

        still_missing = [s for s in missing_slots if s not in entities]

        if still_missing:
            # Partial fill — keep pending and return a clarify message
            updated_params = {**existing_params, **entities}
            context.slots["_pending_action"] = {
                "intent_name": pending_intent_name,
                "missing_slots": still_missing,
                "tool_name": tool_name,
                "params": updated_params,
            }
            prompt = self._slot_prompt(still_missing)
            return AgentMessage(
                message_type="text",
                payload={"content": prompt, "question": prompt},
                text_fallback=prompt,
            )

        # All slots filled — build a synthetic intent and execute directly
        merged_params = {**existing_params, **entities}
        context.slots.pop("_pending_action", None)

        pending_intent = Intent(
            name=pending_intent_name,
            display_name=pending_intent_name,
            confidence=1.0,
            # Synthetic intent recovered from a persisted pending action; the
            # "context" source is a deliberate runtime marker that flows into
            # response meta (intent_source) and is outside the Intent.source
            # Literal owned by core/types.py.
            source="context",  # type: ignore[arg-type]
            entities=merged_params,
        )
        tools = await host._tool_injector.inject(pending_intent, context)

        # Build a tool_call action with the complete params
        if tool_name:
            action = Action(
                type="tool_call",
                payload={
                    "tool_name": tool_name,
                    "params": merged_params,
                    "call_id": f"call-{pending_intent_name}",
                },
            )
            return await host._execute_action(action, context, tools)

        # No tool — use strategy to decide
        action = await host._strategy.decide(pending_intent, context, tools)
        return await host._execute_action(action, context, tools)

    @staticmethod
    def _slot_prompt(missing_slots: list[str]) -> str:
        prompts = {
            "order_id": "请问您的订单号是多少？例如 ORD-001",
            "keyword": "请问您想搜索什么商品？",
            "reason": "请问退款原因是什么？",
            "address": "请问新的收货地址是什么？",
        }
        first = missing_slots[0]
        return prompts.get(first, f"请提供以下信息：{', '.join(missing_slots)}")
