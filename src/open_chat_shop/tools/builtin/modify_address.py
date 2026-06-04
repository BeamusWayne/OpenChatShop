"""modify_address tool -- change the delivery address for an unshipped order."""

from __future__ import annotations

from typing import Any, ClassVar

from open_chat_shop.core.types import SessionContext, ToolPermission, ToolResult
from open_chat_shop.tools.builtin._order_mutation import OrderMutationTool

_SHIPPED_STATUSES = ("shipped", "delivered")


class ModifyAddressTool(OrderMutationTool):
    """Modify the delivery address of an order that has not yet shipped."""

    name: str = "modify_address"
    description: str = (
        "Modify delivery address for an order. Order must not be "
        "shipped. Requires confirmation."
    )
    category: str = "order"
    params_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "order_id": {"type": "string", "description": "The order ID to modify"},
            "address": {"type": "string", "description": "New delivery address"},
            "phone": {"type": "string", "description": "Optional new contact phone number"},
        },
        "required": ["order_id", "address"],
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
        if order["status"] not in _SHIPPED_STATUSES:
            return None
        return (
            f"订单 {order_id} 已发货，无法修改地址",
            (
                f"Cannot modify address: order {order_id} has shipped "
                f"(status: {order['status']})"
            ),
        )

    def _perform(
        self,
        order: dict[str, Any],
        order_id: str,
        params: dict[str, Any],
        context: SessionContext,
    ) -> dict[str, Any]:
        new_address = params["address"]
        new_phone = params.get("phone")
        self._order_repo.save_snapshot(order_id)
        _, old_address = self._order_repo.update_address(order_id, new_address, new_phone)
        return {
            "order_id": order_id,
            "old_address": old_address,
            "new_address": new_address,
        }

    async def compensate(self, params: dict[str, Any], context: SessionContext) -> None:
        """Restore the order address on failure."""
        self._order_repo.restore_snapshot(params["order_id"])

    def format_result(self, result: ToolResult) -> str:
        data = result.data
        if not data:
            return "地址已修改"
        lines = [
            f"订单 {data['order_id']} 的收货地址已更新。",
            f"原地址：{data.get('old_address', '未知')}",
            f"新地址：{data.get('new_address', '未知')}",
        ]
        return "\n".join(lines)
