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
            return ToolResult(success=False, error=f"未找到订单 {order_id}")

        logistics = LOGISTICS.get(order_id)
        if logistics is None:
            return ToolResult(
                success=False,
                error=f"订单 {order_id} 暂无物流信息",
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

    _STATUS_MAP: dict[str, str] = {
        "picked_up": "已揽收",
        "in_transit": "运输中",
        "out_for_delivery": "派送中",
        "delivered": "已签收",
    }

    def format_result(self, result: ToolResult) -> str:
        data = result.data
        if not data:
            return "操作成功"
        lines = [
            f"订单 {data['order_id']} 物流信息",
            f"承运商：{data['carrier']}",
            f"运单号：{data['tracking_number']}",
            "物流轨迹：",
        ]
        for entry in data.get("timeline", []):
            status = self._STATUS_MAP.get(entry.get("status", ""), entry.get("status", ""))
            lines.append(f"  {entry['time']}  {status}  {entry['location']}")
        return "\n".join(lines)
