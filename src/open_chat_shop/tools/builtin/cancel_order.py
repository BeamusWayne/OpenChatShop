"""cancel_order tool -- cancel a pending or processing order."""

from __future__ import annotations

from typing import Any, ClassVar

from open_chat_shop.core.types import SessionContext, ToolPermission, ToolResult
from open_chat_shop.tools.builtin._order_mutation import OrderMutationTool


class CancelOrderTool(OrderMutationTool):
    """Cancel an order that is in pending or processing status."""

    name: str = "cancel_order"
    description: str = (
        "Cancel an order. Only pending or processing orders can be "
        "cancelled. Requires confirmation."
    )
    category: str = "order"
    params_schema: ClassVar[dict[str, Any]] = {
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

    def _status_reasons(
        self, order: dict[str, Any], order_id: str
    ) -> tuple[str | None, str | None] | None:
        if order["status"] in ("pending", "processing"):
            return None
        return (
            f"订单 {order_id} 当前状态不可取消",
            f"Order {order_id} cannot be cancelled (status: {order['status']})",
        )

    def _perform(
        self,
        order: dict[str, Any],
        order_id: str,
        params: dict[str, Any],
        context: SessionContext,
    ) -> dict[str, Any]:
        reason = params["reason"]
        self._order_repo.save_snapshot(order_id)
        self._order_repo.update_status(order_id, "cancelled", cancellation_reason=reason)
        return {
            "order_id": order_id,
            "status": "cancelled",
            "reason": reason,
        }

    async def compensate(self, params: dict[str, Any], context: SessionContext) -> None:
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
