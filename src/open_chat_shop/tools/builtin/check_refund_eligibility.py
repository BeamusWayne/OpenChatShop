"""check_refund_eligibility tool -- verify if an order can be refunded."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from open_chat_shop.core.tool import BaseTool
from open_chat_shop.core.types import CheckResult, SessionContext, ToolPermission, ToolResult
from open_chat_shop.storage.repositories.abc import OrderRepository
from open_chat_shop.storage.repositories.memory import InMemoryOrderRepository


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

    def __init__(self, order_repo: OrderRepository | None = None) -> None:
        self._order_repo = order_repo or InMemoryOrderRepository()

    async def pre_check(self, params: dict, context: SessionContext) -> CheckResult:
        order_id = params["order_id"]
        order = self._order_repo.get(order_id)
        if order is None:
            return CheckResult(passed=False, reason=f"订单 {order_id} 不存在")
        if order["status"] == "refunded":
            return CheckResult(passed=False, reason=f"订单 {order_id} 已退款")
        return CheckResult(passed=True)

    async def execute(self, params: dict, context: SessionContext) -> ToolResult:
        order_id = params["order_id"]
        order = self._order_repo.get(order_id)
        if order is None:
            return ToolResult(success=False, error=f"Order {order_id} not found")

        if order["status"] == "refunded":
            return ToolResult(
                success=True,
                data={
                    "eligible": False,
                    "reason": "该订单已退款",
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
                "reason": "订单在30天退款期限内",
                "deadline": deadline.isoformat(),
            },
        )

    def format_result(self, result: ToolResult) -> str:
        data = result.data
        if not data:
            return "无法获取退款资格信息"
        eligible = data.get("eligible", False)
        reason = data.get("reason", "")
        if eligible:
            lines = [
                "该订单可以申请退款。",
                f"原因：{reason}",
            ]
            deadline = data.get("deadline")
            if deadline:
                try:
                    dt = datetime.fromisoformat(deadline)
                    formatted = dt.strftime("%Y年%m月%d日")
                except (ValueError, TypeError):
                    formatted = deadline
                lines.append(f"退款截止日期：{formatted}")
        else:
            lines = [
                "该订单暂不可退款。",
                f"原因：{reason}",
            ]
        return "\n".join(lines)
