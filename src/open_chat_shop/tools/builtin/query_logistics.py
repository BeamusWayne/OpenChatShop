"""query_logistics tool -- look up logistics/tracking by order ID."""

from __future__ import annotations

from typing import Any

from open_chat_shop.core.tool import BaseTool
from open_chat_shop.core.types import SessionContext, ToolPermission, ToolResult

from open_chat_shop.tools.builtin._mock_data import LOGISTICS, ORDERS


class QueryLogisticsTool(BaseTool):
    """Query logistics tracking information for an order."""

    name: str = "query_logistics"
    description: str = "Query logistics tracking by order ID. Returns carrier, tracking number, and delivery timeline."
    category: str = "logistics"
    params_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "order_id": {"type": "string", "description": "The order ID to track"},
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

        if order_id not in ORDERS:
            return ToolResult(success=False, error=f"Order {order_id} not found")

        logistics = LOGISTICS.get(order_id)
        if logistics is None:
            return ToolResult(
                success=False,
                error=f"No logistics information available for order {order_id}",
            )

        return ToolResult(
            success=True,
            data={
                "order_id": logistics["order_id"],
                "carrier": logistics["carrier"],
                "tracking_number": logistics["tracking_number"],
                "timeline": logistics["timeline"],
            },
        )
