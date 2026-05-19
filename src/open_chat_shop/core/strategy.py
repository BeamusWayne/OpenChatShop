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
    - If intent is fallback -> clarify
    - If tools are available and intent requires tool -> tool_call
    - If required tool params are missing -> clarify with prompt
    - If intent requires confirmation (from tool permissions) -> confirm
    - Otherwise -> reply
    """

    _MISSING_PARAM_PROMPTS: dict[str, dict[str, str]] = {
        "order_id": "请问您的订单号是多少？例如 ORD-001",
        "keyword": "请问您想搜索什么商品？",
        "new_address": "请问新的收货地址是什么？",
        "reason": "请问退款原因是什么？",
    }

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

        if intent.name == "greeting":
            return Action(
                type="reply",
                payload={
                    "content": "您好！我是智能客服助手，可以帮您查询订单、搜索商品、处理退换货等。请问有什么可以帮您？",
                    "message_type": "text",
                },
            )

        if intent.name == "thanks":
            return Action(
                type="reply",
                payload={
                    "content": "不客气！如果还有其他问题，随时可以问我。",
                    "message_type": "text",
                },
            )

        if tools:
            tool = tools[0]
            params = dict(intent.entities)

            # Check for missing required params
            schema = tool.params_schema
            required = schema.get("required", [])
            missing = [r for r in required if r not in params]
            if missing:
                prompt = self._MISSING_PARAM_PROMPTS.get(
                    missing[0], f"请提供以下信息：{', '.join(missing)}"
                )
                return Action(
                    type="clarify",
                    payload={"question": prompt, "missing_slots": missing},
                )

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
                            "params": params,
                            "call_id": f"call-{intent.name}",
                        },
                    },
                )

            return Action(
                type="tool_call",
                payload={
                    "tool_name": tool.name,
                    "params": params,
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
