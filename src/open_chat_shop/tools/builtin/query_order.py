"""query_order tool -- look up order status by order ID."""

from __future__ import annotations

from typing import Any

from open_chat_shop.core.tool import BaseTool
from open_chat_shop.core.types import SessionContext, ToolPermission, ToolResult
from open_chat_shop.storage.repositories.abc import OrderRepository
from open_chat_shop.storage.repositories.memory import InMemoryOrderRepository


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

    def __init__(self, order_repo: OrderRepository | None = None) -> None:
        self._order_repo = order_repo or InMemoryOrderRepository()

    async def execute(self, params: dict, context: SessionContext) -> ToolResult:
        order_id = params["order_id"]
        order = self._order_repo.get_for_user(order_id, context.user_id)
        if order is None:
            return ToolResult(success=False, error=f"未找到订单 {order_id}，请检查订单号是否正确")
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

    _STATUS_MAP: dict[str, str] = {
        "pending": "待处理",
        "processing": "处理中",
        "shipped": "已发货",
        "delivered": "已送达",
        "refunded": "已退款",
        "cancelled": "已取消",
    }

    def format_result(self, result: ToolResult) -> str:
        data = result.data
        if not data:
            return "操作成功"
        status = self._STATUS_MAP.get(data.get("status", ""), data.get("status", ""))
        lines = [f"订单号：{data['order_id']}", f"状态：{status}"]
        items = data.get("items", [])
        if items:
            lines.append("商品：")
            for item in items:
                lines.append(f"  - {item['name']} x{item['quantity']}  ¥{item['price']:.2f}")
        lines.append(f"合计：¥{data.get('total_amount', 0):.2f}")
        lines.append(f"下单时间：{data.get('created_at', '')}")
        return "\n".join(lines)
