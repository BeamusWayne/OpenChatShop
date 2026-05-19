"""Built-in e-commerce tools for OpenChatShop.

Provides 8 tools covering order management, logistics, product search,
refund operations, address modification, and human handoff.
"""

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
]
