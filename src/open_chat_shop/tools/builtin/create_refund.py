"""create_refund tool -- create a refund request for an order."""

from __future__ import annotations

from typing import Any

from open_chat_shop.core.tool import BaseTool
from open_chat_shop.core.types import CheckResult, SessionContext, ToolPermission, ToolResult
from open_chat_shop.storage.repositories.abc import OrderRepository, RefundRepository
from open_chat_shop.storage.repositories.memory import (
    InMemoryOrderRepository,
    InMemoryRefundRepository,
)


class CreateRefundTool(BaseTool):
    """Create a refund request for an order."""

    name: str = "create_refund"
    description: str = "Create a refund request. Requires confirmation for amounts over 500."
    category: str = "refund"
    params_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "order_id": {"type": "string", "description": "The order ID to refund"},
            "reason": {"type": "string", "description": "Reason for the refund"},
            "amount": {"type": "number", "description": "Optional specific refund amount"},
        },
        "required": ["order_id", "reason"],
        "additionalProperties": False,
    }
    permissions: ToolPermission = ToolPermission(
        required_roles=["customer"],
        idempotent=False,
        requires_confirmation=True,
        confirmation_threshold={"field": "amount", "gt": 500},
    )

    def __init__(
        self,
        order_repo: OrderRepository | None = None,
        refund_repo: RefundRepository | None = None,
    ) -> None:
        self._order_repo = order_repo or InMemoryOrderRepository()
        self._refund_repo = refund_repo or InMemoryRefundRepository()

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
        reason = params["reason"]
        amount = params.get("amount")

        order = self._order_repo.get(order_id)
        if order is None:
            return ToolResult(success=False, error=f"Order {order_id} not found")

        refund_amount = amount if amount is not None else order["total_amount"]

        record = self._refund_repo.create(order_id, refund_amount, reason)

        return ToolResult(
            success=True,
            data={
                "refund_id": record["refund_id"],
                "status": record["status"],
                "amount": record["amount"],
            },
        )

    async def compensate(self, params: dict, context: SessionContext) -> None:
        """Cancel the refund on failure by removing it from the store."""
        self._refund_repo.delete_processing_by_order(params["order_id"])

    _REFUND_STATUS_MAP: dict[str, str] = {
        "processing": "处理中",
        "approved": "已批准",
        "rejected": "已拒绝",
        "completed": "已完成",
        "cancelled": "已取消",
    }

    def format_result(self, result: ToolResult) -> str:
        data = result.data
        if not data:
            return "退款申请已提交"
        status = self._REFUND_STATUS_MAP.get(data.get("status", ""), data.get("status", ""))
        lines = [
            f"退款单号：{data['refund_id']}",
            f"退款状态：{status}",
            f"退款金额：¥{data.get('amount', 0):.2f}",
        ]
        return "\n".join(lines)
