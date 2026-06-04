"""Strategy engine — decides the next action based on intent and context."""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, ClassVar

from open_chat_shop.core.types import Action, Intent, SessionContext, ToolPermission

logger = logging.getLogger(__name__)


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

    _MISSING_PARAM_PROMPTS: ClassVar[dict[str, str]] = {
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
                    "content": (
                        "您好！我是智能客服助手，可以帮您查询订单、搜索商品、"
                        "处理退换货等。请问有什么可以帮您？"
                    ),
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
            tool = self._select_tool(tools, intent.name)
            schema = tool.params_schema
            # Only feed schema-relevant entities to the tool. Persisted context
            # slots (e.g. a stale order_id from a prior query) and internal flags
            # like ``_clarifying_response`` are merged into ``intent.entities`` by
            # the intent engine, but the tool's JSON Schema sets
            # ``additionalProperties: False`` — so passing those through makes a
            # perfectly valid call fail validation and the user is wrongly told
            # their info is incomplete. Whitelist the tool's declared properties
            # and drop internal ``_``-prefixed keys before building params.
            params = self._schema_params(intent.entities, schema)

            # Check for missing required params
            required = schema.get("required", [])
            missing = [r for r in required if r not in params]
            if missing:
                prompt = self._MISSING_PARAM_PROMPTS.get(
                    missing[0], f"请提供以下信息：{', '.join(missing)}"
                )
                return Action(
                    type="clarify",
                    payload={
                        "question": prompt,
                        "missing_slots": missing,
                        "_pending_action": {
                            "intent_name": intent.name,
                            "missing_slots": missing,
                            "tool_name": tool.name,
                            "params": params,
                        },
                    },
                )

            # Check if tool requires confirmation
            if hasattr(tool, "permissions") and self._needs_confirmation(
                tool.permissions, params
            ):
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

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _select_tool(tools: list[Any], intent_name: str) -> Any:
        """Pick the tool that matches the intent by name, else the first.

        A routing rule can inject several tools in a fixed order (e.g. refunds
        resolve to ``[check_refund_eligibility, create_refund]``). Blindly using
        ``tools[0]`` makes an explicit ``create_refund`` intent run the
        read-only eligibility check instead of creating the refund — the write
        (and its confirmation gate) never happens. Prefer the tool whose name
        equals the intent so each intent triggers its own action.
        """
        for tool in tools:
            if getattr(tool, "name", None) == intent_name:
                return tool
        return tools[0]

    @staticmethod
    def _schema_params(
        entities: dict[str, Any], schema: dict[str, Any]
    ) -> dict[str, Any]:
        """Project *entities* onto the tool schema's declared properties.

        Drops internal ``_``-prefixed keys and any key not declared in the
        schema so that strict (``additionalProperties: False``) tool schemas do
        not reject otherwise-valid calls because of persisted context slots.
        """
        allowed = schema.get("properties", {})
        return {
            key: value
            for key, value in entities.items()
            if not key.startswith("_") and key in allowed
        }

    @staticmethod
    def _needs_confirmation(
        permissions: ToolPermission, params: dict[str, Any]
    ) -> bool:
        """Decide whether the tool call must be confirmed by the user.

        Honours ``confirmation_threshold``: when a tool declares one, only
        require confirmation if the named field's value exceeds the bound.
        The threshold is evaluated safe-side — if the field is absent (so the
        true value is unknown) confirmation is still required. Without a
        threshold, ``requires_confirmation`` applies unconditionally.
        """
        if not permissions.requires_confirmation:
            return False

        threshold = permissions.confirmation_threshold
        if not threshold:
            return True

        field = threshold.get("field")
        if field is None or field not in params:
            # Unknown value on a write that asked to be gated -> confirm.
            return True

        value = params[field]
        if "gt" in threshold and isinstance(value, (int, float)):
            return bool(value > threshold["gt"])
        # Unrecognised threshold shape -> fall back to gating (safe-side).
        return True
