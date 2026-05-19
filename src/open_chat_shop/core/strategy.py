"""Strategy engine — decides the next action based on intent and context."""
from __future__ import annotations

from abc import ABC, abstractmethod
import logging

from open_chat_shop.core.types import Intent, SessionContext, Action

logger = logging.getLogger(__name__)

# Avoid circular import — BaseTool is defined in tool.py
from typing import TYPE_CHECKING, Any
if TYPE_CHECKING:
    from open_chat_shop.core.tool import BaseTool


class Strategy(ABC):
    """Abstract strategy engine for deciding next actions."""

    @abstractmethod
    async def decide(
        self,
        intent: Intent,
        context: SessionContext,
        tools: list[Any],
    ) -> Action:
        """Decide the next action based on intent, context, and available tools."""


class RuleBasedStrategy(Strategy):
    """Simple rule-based strategy for MVP.

    Decision logic:
    - If intent is fallback → clarify
    - If tools are available and intent requires tool → tool_call
    - If intent requires confirmation (from tool permissions) → confirm
    - Otherwise → reply
    """

    async def decide(
        self,
        intent: Intent,
        context: SessionContext,
        tools: list[Any],
    ) -> Action:
        if intent.name == "fallback":
            return Action(
                type="clarify",
                payload={
                    "question": "抱歉，我不太理解您的问题。您是想查询订单、搜索商品还是其他？",
                    "missing_slots": [],
                },
            )

        if intent.name == "handoff_to_human":
            return Action(
                type="transfer",
                payload={"reason": "用户请求转人工", "department": "客服"},
            )

        if tools:
            tool = tools[0]
            # Check if tool requires confirmation
            if hasattr(tool, "permissions") and tool.permissions.requires_confirmation:
                return Action(
                    type="confirm",
                    payload={
                        "title": f"确认执行：{tool.description}",
                        "description": f"即将执行 {tool.name}，请确认。",
                        "pending_action": {
                            "type": "tool_call",
                            "tool_name": tool.name,
                            "params": intent.entities,
                            "call_id": f"call-{intent.name}",
                        },
                    },
                )

            return Action(
                type="tool_call",
                payload={
                    "tool_name": tool.name,
                    "params": intent.entities,
                    "call_id": f"call-{intent.name}",
                },
            )

        return Action(
            type="reply",
            payload={
                "content": f"我理解您想{intent.display_name}，请稍等。",
                "message_type": "text",
            },
        )
