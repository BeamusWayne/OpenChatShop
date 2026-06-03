"""cancel_order tool -- cancel a pending or processing order."""

from __future__ import annotations

from typing import Any

from open_chat_shop.core.tool import BaseTool
from open_chat_shop.core.types import CheckResult, SessionContext, ToolPermission, ToolResult
from open_chat_shop.storage.repositories.abc import OrderRepository
from open_chat_shop.storage.repositories.memory import InMemoryOrderRepository


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

    def __init__(self, order_repo: OrderRepository | None = None) -> None:
        self._order_repo = order_repo or InMemoryOrderRepository()

    async def pre_check(self, params: dict, context: SessionContext) -> CheckResult:
        order_id = params["order_id"]
        order = self._order_repo.get_for_user(order_id, context.user_id)
        if order is None:
            return CheckResult(passed=False, reason=f"订单 {order_id} 不存在")
        if order["status"] not in ("pending", "processing"):
            return CheckResult(
                passed=False,
                reason=f"订单 {order_id} 当前状态不可取消",
            )
        return CheckResult(passed=True)

    async def execute(self, params: dict, context: SessionContext) -> ToolResult:
        order_id = params["order_id"]
        reason = params["reason"]

        order = self._order_repo.get_for_user(order_id, context.user_id)
        if order is None:
            return ToolResult(success=False, error=f"Order {order_id} not found")

        if order["status"] not in ("pending", "processing"):
            return ToolResult(
                success=False,
                error=f"Order {order_id} cannot be cancelled (status: {order['status']})",
            )

        self._order_repo.save_snapshot(order_id)
        self._order_repo.update_status(order_id, "cancelled", cancellation_reason=reason)

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
        self._order_repo.restore_snapshot(params["order_id"])

    def format_result(self, result: ToolResult) -> str:
        data = result.data
        if not data:
            return "订单已取消"
        lines = [
            f"订单 {data['order_id']} 已成功取消。",
            f"取消原因：{data.get('reason', '未说明')}",
        ]
        return "\n".join(lines)
