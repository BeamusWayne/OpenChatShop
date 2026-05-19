"""Map ToolResult to AgentMessage — feat-029.

Converts raw tool output into the correct rich-message type
so the channel layer can render it.
"""
from __future__ import annotations

from typing import Any

from commerce_agent.core.types import AgentMessage, SessionContext, ToolResult


def _text(content: str, suggestions: list[str] | None = None) -> AgentMessage:
    """Shorthand for a plain-text AgentMessage."""
    return AgentMessage(
        message_type="text",
        payload={"content": content},
        text_fallback=content,
        suggestions=suggestions or [],
    )


def _map_query_order(data: dict[str, Any]) -> AgentMessage:
    return AgentMessage(
        message_type="order_card",
        payload={
            "order_id": data["order_id"],
            "status": data["status"],
            "items": data.get("items", []),
            "total_amount": data.get("total_amount"),
        },
        text_fallback=f"订单 {data['order_id']} 状态：{data['status']}",
        suggestions=["查看物流", "申请退款"],
    )


def _map_query_logistics(data: dict[str, Any]) -> AgentMessage:
    steps = data.get("steps", [])
    return AgentMessage(
        message_type="logistics_timeline",
        payload={"order_id": data["order_id"], "steps": steps},
        text_fallback=f"订单 {data['order_id']} 物流信息已查询",
    )


def _map_search_product(data: dict[str, Any]) -> AgentMessage:
    products = data.get("products", [])
    total = data.get("total", len(products))
    return AgentMessage(
        message_type="product_list",
        payload={"products": products, "total": total},
        text_fallback=f"找到 {total} 个商品",
        suggestions=["查看详情", "加入购物车"],
    )


def _map_check_refund_eligibility(data: dict[str, Any]) -> AgentMessage:
    eligible = data.get("eligible", False)
    reason = data.get("reason", "")
    if eligible:
        content = "您的订单符合退款条件，可以申请退款。"
    else:
        content = f"您的订单暂不支持退款。原因：{reason}" if reason else "您的订单暂不支持退款。"
    return _text(content)


def _map_create_refund(data: dict[str, Any]) -> AgentMessage:
    refund_id = data.get("refund_id", "")
    amount = data.get("amount", "")
    content = f"退款已创建，退款单号：{refund_id}，金额：{amount}。"
    return _text(content)


def _map_cancel_order(data: dict[str, Any]) -> AgentMessage:
    order_id = data.get("order_id", "")
    content = f"订单 {order_id} 已取消。"
    return _text(content, suggestions=["重新下单"])


def _map_modify_address(data: dict[str, Any]) -> AgentMessage:
    order_id = data.get("order_id", "")
    content = f"订单 {order_id} 的收货地址已更新。"
    return _text(content)


def _map_handoff_to_human(data: dict[str, Any]) -> AgentMessage:
    return AgentMessage(
        message_type="transfer",
        payload={
            "reason": data.get("reason", ""),
            "department": data.get("department", ""),
            "estimated_wait_seconds": data.get("estimated_wait_seconds", 60),
        },
        text_fallback="正在为您转接人工客服，请稍候。",
    )


_MAPPERS: dict[str, Any] = {
    "query_order": _map_query_order,
    "query_logistics": _map_query_logistics,
    "search_product": _map_search_product,
    "check_refund_eligibility": _map_check_refund_eligibility,
    "create_refund": _map_create_refund,
    "cancel_order": _map_cancel_order,
    "modify_address": _map_modify_address,
    "handoff_to_human": _map_handoff_to_human,
}


class ToolResponseMapper:
    """Convert ToolResult into the correct AgentMessage type."""

    def map(self, tool_name: str, result: ToolResult, context: SessionContext) -> AgentMessage:
        """Dispatch by *tool_name* and return a rich AgentMessage."""
        # Error result: always text with error message
        if not result.success:
            return _text(f"操作失败：{result.error or '未知错误'}")

        # Null data: generic success text
        if result.data is None:
            return _text("操作成功。")

        # Known tool: use dedicated mapper
        mapper = _MAPPERS.get(tool_name)
        if mapper is not None:
            return mapper(result.data)

        # Unknown tool: fallback text with data dump
        return _text(str(result.data))
