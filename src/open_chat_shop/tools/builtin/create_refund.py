"""create_refund tool -- create a refund request for an order."""

from __future__ import annotations

from typing import Any

from open_chat_shop.core.tool import BaseTool
from open_chat_shop.core.types import CheckResult, SessionContext, ToolPermission, ToolResult

from open_chat_shop.tools.builtin._mock_data import ORDERS


class CreateRefundTool(BaseTool):
    """Create a refund request for an order."""

    name: str = "create_refund"
    description: str = "Create a refund request. Requires confirmation for amounts over 500."
    category: str = "refund"
    params_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "order_id": {"type": "string", "description": "The order ID to refund"},
            "reason": {"type": "string", "description": "Reason for the refund"},
            "amount": {"type": "number", "description": "Optional specific refund amount"},
        },
        "required": ["order_id", "reason"],
        "additionalProperties": False,
    }
    permissions: ToolPermission = ToolPermission(
        required_roles=["customer"],
        idempotent=False,
        requires_confirmation=True,
        confirmation_threshold={"field": "amount", "gt": 500},
    )

    async def pre_check(self, params: dict, context: SessionContext) -> CheckResult:
        order_id = params["order_id"]
        order = ORDERS.get(order_id)
        if order is None:
            return CheckResult(passed=False, reason=f"Order {order_id} does not exist")
        if order["status"] == "refunded":
            return CheckResult(passed=False, reason=f"Order {order_id} has already been refunded")
        return CheckResult(passed=True)

    async def execute(self, params: dict, context: SessionContext) -> ToolResult:
        import open_chat_shop.tools.builtin._mock_data as _md

        order_id = params["order_id"]
        reason = params["reason"]
        amount = params.get("amount")

        order = ORDERS.get(order_id)
        if order is None:
            return ToolResult(success=False, error=f"Order {order_id} not found")

        refund_amount = amount if amount is not None else order["total_amount"]

        _md.REFUND_COUNTER += 1
        refund_id = f"REF-{_md.REFUND_COUNTER:04d}"

        refund_record = {
            "refund_id": refund_id,
            "order_id": order_id,
            "amount": refund_amount,
            "reason": reason,
            "status": "processing",
        }
        _md.REFUNDS[refund_id] = refund_record

        return ToolResult(
            success=True,
            data={
                "refund_id": refund_id,
                "status": "processing",
                "amount": refund_amount,
            },
        )

    async def compensate(self, params: dict, context: SessionContext) -> None:
        """Cancel the refund on failure by removing it from the store."""
        import open_chat_shop.tools.builtin._mock_data as _md

        order_id = params["order_id"]
        to_remove = [
            rid for rid, ref in _md.REFUNDS.items()
            if ref["order_id"] == order_id and ref["status"] == "processing"
        ]
        for rid in to_remove:
            del _md.REFUNDS[rid]
