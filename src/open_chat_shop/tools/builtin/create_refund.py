"""create_refund tool -- create a refund request for an order."""

from __future__ import annotations

from typing import Any, ClassVar

from open_chat_shop.core.types import SessionContext, ToolPermission, ToolResult
from open_chat_shop.storage.repositories.abc import OrderRepository, RefundRepository
from open_chat_shop.storage.repositories.memory import InMemoryRefundRepository
from open_chat_shop.tools.builtin._order_mutation import OrderMutationTool


class CreateRefundTool(OrderMutationTool):
    """Create a refund request for an order."""

    name: str = "create_refund"
    description: str = "Create a refund request. Requires confirmation for amounts over 500."
    category: str = "refund"
    params_schema: ClassVar[dict[str, Any]] = {
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
        super().__init__(order_repo)
        self._refund_repo = refund_repo or InMemoryRefundRepository()

    def _status_reasons(
        self, order: dict[str, Any], order_id: str
    ) -> tuple[str | None, str | None] | None:
        # Rejected at pre_check (zh) only; execute historically did not re-guard
        # an already-refunded order, so the English entry stays None.
        if order["status"] == "refunded":
            return (f"订单 {order_id} 已退款", None)
        return None

    def _perform(
        self,
        order: dict[str, Any],
        order_id: str,
        params: dict[str, Any],
        context: SessionContext,
    ) -> dict[str, Any]:
        reason = params["reason"]
        amount = params.get("amount")
        refund_amount = amount if amount is not None else order["total_amount"]
        record = self._refund_repo.create(order_id, refund_amount, reason)
        return {
            "refund_id": record["refund_id"],
            "status": record["status"],
            "amount": record["amount"],
        }

    async def compensate(self, params: dict[str, Any], context: SessionContext) -> None:
        """Cancel the refund on failure by removing it from the store."""
        self._refund_repo.delete_processing_by_order(params["order_id"])

    _REFUND_STATUS_MAP: ClassVar[dict[str, str]] = {
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
