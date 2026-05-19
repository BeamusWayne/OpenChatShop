"""query_order tool -- look up order status by order ID."""

from __future__ import annotations

from typing import Any

from open_chat_shop.core.tool import BaseTool
from open_chat_shop.core.types import SessionContext, ToolPermission, ToolResult

from open_chat_shop.tools.builtin._mock_data import ORDERS


class QueryOrderTool(BaseTool):
    """Query order status, items, and total amount."""

    name: str = "query_order"
    description: str = "Query order status by order ID. Returns order details including status, items, and total amount."
    category: str = "order"
    params_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "order_id": {"type": "string", "description": "The order ID to query"},
        },
        "required": ["order_id"],
        "additionalProperties": False,
    }
    permissions: ToolPermission = ToolPermission(
        required_roles=["customer"],
        idempotent=True,
    )

    async def execute(self, params: dict, context: SessionContext) -> ToolResult:
        order_id = params["order_id"]
        order = ORDERS.get(order_id)
        if order is None:
            return ToolResult(success=False, error=f"Order {order_id} not found")
        return ToolResult(
            success=True,
            data={
                "order_id": order["order_id"],
                "status": order["status"],
                "items": order["items"],
                "total_amount": order["total_amount"],
                "created_at": order["created_at"],
            },
        )
