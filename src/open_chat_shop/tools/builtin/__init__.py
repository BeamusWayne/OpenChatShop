"""Built-in e-commerce tools for OpenChatShop.

Provides 8 tools covering order management, logistics, product search,
refund operations, address modification, and human handoff.
"""
from __future__ import annotations

from typing import Any

from open_chat_shop.core.tool import BaseTool
from open_chat_shop.tools.builtin.cancel_order import CancelOrderTool
from open_chat_shop.tools.builtin.check_refund_eligibility import CheckRefundEligibilityTool
from open_chat_shop.tools.builtin.create_refund import CreateRefundTool
from open_chat_shop.tools.builtin.handoff_to_human import HandoffToHumanTool
from open_chat_shop.tools.builtin.modify_address import ModifyAddressTool
from open_chat_shop.tools.builtin.query_logistics import QueryLogisticsTool
from open_chat_shop.tools.builtin.query_order import QueryOrderTool
from open_chat_shop.tools.builtin.search_product import SearchProductTool

ALL_TOOLS: list[type] = [
    QueryOrderTool,
    QueryLogisticsTool,
    SearchProductTool,
    CheckRefundEligibilityTool,
    CreateRefundTool,
    CancelOrderTool,
    ModifyAddressTool,
    HandoffToHumanTool,
]


def create_tools(repos: dict[str, Any] | None = None) -> list[BaseTool]:
    """Instantiate all tools with the given repositories.

    When *repos* is None or missing keys, each tool falls back to
    its default InMemory repository — so ``create_tools()`` with no
    arguments behaves identically to ``[cls() for cls in ALL_TOOLS]``.
    """
    repos = repos or {}
    return [
        QueryOrderTool(order_repo=repos.get("order")),
        QueryLogisticsTool(
            order_repo=repos.get("order"),
            logistics_repo=repos.get("logistics"),
        ),
        SearchProductTool(product_repo=repos.get("product")),
        CheckRefundEligibilityTool(order_repo=repos.get("order")),
        CreateRefundTool(
            order_repo=repos.get("order"),
            refund_repo=repos.get("refund"),
        ),
        CancelOrderTool(order_repo=repos.get("order")),
        ModifyAddressTool(order_repo=repos.get("order")),
        HandoffToHumanTool(handoff_repo=repos.get("handoff")),
    ]


__all__ = [
    "ALL_TOOLS",
    "CancelOrderTool",
    "CheckRefundEligibilityTool",
    "CreateRefundTool",
    "HandoffToHumanTool",
    "ModifyAddressTool",
    "QueryLogisticsTool",
    "QueryOrderTool",
    "SearchProductTool",
    "create_tools",
]
