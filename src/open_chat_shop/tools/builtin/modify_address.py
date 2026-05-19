"""modify_address tool -- change the delivery address for an unshipped order."""

from __future__ import annotations

import copy
from typing import Any

from open_chat_shop.core.tool import BaseTool
from open_chat_shop.core.types import CheckResult, SessionContext, ToolPermission, ToolResult

from open_chat_shop.tools.builtin._mock_data import ORDERS

# Snapshot of original orders for compensation restore
_ORDER_SNAPSHOTS: dict[str, dict] = {}


class ModifyAddressTool(BaseTool):
    """Modify the delivery address of an order that has not yet shipped."""

    name: str = "modify_address"
    description: str = "Modify delivery address for an order. Order must not be shipped. Requires confirmation."
    category: str = "order"
    params_schema: dict[str, Any] = {
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

    async def pre_check(self, params: dict, context: SessionContext) -> CheckResult:
        order_id = params["order_id"]
        order = ORDERS.get(order_id)
        if order is None:
            return CheckResult(passed=False, reason=f"Order {order_id} does not exist")
        shipped_statuses = ("shipped", "delivered")
        if order["status"] in shipped_statuses:
            return CheckResult(
                passed=False,
                reason=f"Order {order_id} has already shipped (status: {order['status']})",
            )
        return CheckResult(passed=True)

    async def execute(self, params: dict, context: SessionContext) -> ToolResult:
        order_id = params["order_id"]
        new_address = params["address"]
        new_phone = params.get("phone")

        order = ORDERS.get(order_id)
        if order is None:
            return ToolResult(success=False, error=f"Order {order_id} not found")

        shipped_statuses = ("shipped", "delivered")
        if order["status"] in shipped_statuses:
            return ToolResult(
                success=False,
                error=f"Cannot modify address: order {order_id} has shipped (status: {order['status']})",
            )

        # Save snapshot for compensation
        _ORDER_SNAPSHOTS[order_id] = copy.deepcopy(order)

        old_address = order["address"]
        order["address"] = new_address
        if new_phone is not None:
            order["phone"] = new_phone

        return ToolResult(
            success=True,
            data={
                "order_id": order_id,
                "old_address": old_address,
                "new_address": new_address,
            },
        )

    async def compensate(self, params: dict, context: SessionContext) -> None:
        """Restore the order address on failure."""
        order_id = params["order_id"]
        snapshot = _ORDER_SNAPSHOTS.pop(order_id, None)
        if snapshot and order_id in ORDERS:
            ORDERS[order_id] = snapshot

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
