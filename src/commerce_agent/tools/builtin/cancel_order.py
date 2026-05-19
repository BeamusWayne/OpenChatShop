"""cancel_order tool -- cancel a pending or processing order."""

from __future__ import annotations

import copy
from typing import Any

from commerce_agent.core.tool import BaseTool
from commerce_agent.core.types import CheckResult, SessionContext, ToolPermission, ToolResult

from commerce_agent.tools.builtin._mock_data import ORDERS

# Snapshot of original orders for compensation restore
_ORDER_SNAPSHOTS: dict[str, dict] = {}


class CancelOrderTool(BaseTool):
    """Cancel an order that is in pending or processing status."""

    name: str = "cancel_order"
    description: str = "Cancel an order. Only pending or processing orders can be cancelled. Requires confirmation."
    category: str = "order"
    params_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "order_id": {"type": "string", "description": "The order ID to cancel"},
            "reason": {"type": "string", "description": "Reason for cancellation"},
        },
        "required": ["order_id", "reason"],
        "additionalProperties": False,
    }
    permissions: ToolPermission = ToolPermission(
        required_roles=["customer"],
        idempotent=False,
        requires_confirmation=True,
    )

    async def pre_check(self, params: dict, context: SessionContext) -> CheckResult:
        order_id = params["order_id"]
        order = ORDERS.get(order_id)
        if order is None:
            return CheckResult(passed=False, reason=f"Order {order_id} does not exist")
        if order["status"] not in ("pending", "processing"):
            return CheckResult(
                passed=False,
                reason=f"Order {order_id} cannot be cancelled (current status: {order['status']})",
            )
        return CheckResult(passed=True)

    async def execute(self, params: dict, context: SessionContext) -> ToolResult:
        order_id = params["order_id"]
        reason = params["reason"]

        order = ORDERS.get(order_id)
        if order is None:
            return ToolResult(success=False, error=f"Order {order_id} not found")

        if order["status"] not in ("pending", "processing"):
            return ToolResult(
                success=False,
                error=f"Order {order_id} cannot be cancelled (status: {order['status']})",
            )

        # Save snapshot for compensation
        _ORDER_SNAPSHOTS[order_id] = copy.deepcopy(order)

        # Mutate the mock data store
        order["status"] = "cancelled"
        order["cancellation_reason"] = reason

        return ToolResult(
            success=True,
            data={
                "order_id": order_id,
                "status": "cancelled",
                "reason": reason,
            },
        )

    async def compensate(self, params: dict, context: SessionContext) -> None:
        """Restore the order to its previous state on failure."""
        order_id = params["order_id"]
        snapshot = _ORDER_SNAPSHOTS.pop(order_id, None)
        if snapshot and order_id in ORDERS:
            ORDERS[order_id] = snapshot
