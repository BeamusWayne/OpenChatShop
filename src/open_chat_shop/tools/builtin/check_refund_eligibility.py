"""check_refund_eligibility tool -- verify if an order can be refunded."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from open_chat_shop.core.tool import BaseTool
from open_chat_shop.core.types import CheckResult, SessionContext, ToolPermission, ToolResult

from open_chat_shop.tools.builtin._mock_data import ORDERS


class CheckRefundEligibilityTool(BaseTool):
    """Check whether an order is eligible for a refund."""

    name: str = "check_refund_eligibility"
    description: str = "Check if an order can be refunded. Returns eligibility status, reason, and deadline."
    category: str = "refund"
    params_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "order_id": {"type": "string", "description": "The order ID to check"},
        },
        "required": ["order_id"],
        "additionalProperties": False,
    }
    permissions: ToolPermission = ToolPermission(
        required_roles=["customer"],
        idempotent=True,
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
        order_id = params["order_id"]
        order = ORDERS.get(order_id)
        if order is None:
            return ToolResult(success=False, error=f"Order {order_id} not found")

        if order["status"] == "refunded":
            return ToolResult(
                success=True,
                data={
                    "eligible": False,
                    "reason": "Order has already been refunded",
                    "deadline": None,
                },
            )

        # Mock: refund deadline is 30 days after order creation
        created = datetime.fromisoformat(order["created_at"].replace("Z", "+00:00"))
        deadline = created + timedelta(days=30)

        return ToolResult(
            success=True,
            data={
                "eligible": True,
                "reason": "Order is within the 30-day refund window",
                "deadline": deadline.isoformat(),
            },
        )
