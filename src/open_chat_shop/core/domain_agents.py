"""Default domain specialists for the Multi-Agent split (V2.0 module 1, feat-050).

Three specialists, each carrying only its own tools and a focused prompt so the
model never sees an irrelevant API and prompts stay small:

* **refund** — after-sales (eligibility / refund / cancel);
* **sales** — pre-sales shopping guide (product search);
* **logistics** — order status, shipping, and delivery-address changes.

``handoff_to_human`` is intentionally NOT a specialist tool — it is Triage's
escalation exit (feat-049), not a domain capability.

This module only *defines* the specialists; wiring them into the dialogue flow
is feat-051.
"""
from __future__ import annotations

from open_chat_shop.core.domain_agent import AgentRegistry, DomainAgent

_REFUND = DomainAgent(
    name="refund",
    tool_names=["check_refund_eligibility", "create_refund", "cancel_order"],
    system_prompt=(
        "你是 OpenChatShop 的售后退款专家。只处理退款资格判断、退款发起、订单取消。"
        "依据工具返回的真实数据，用自然、友好的中文简洁回复；金额以工具结果为准，不臆造。"
    ),
)
_SALES = DomainAgent(
    name="sales",
    tool_names=["search_product"],
    system_prompt=(
        "你是 OpenChatShop 的导购专家。只负责商品检索与推荐，不处理退款、物流等售后事务。"
        "根据工具返回的商品数据，用自然、友好的中文为用户挑选合适的商品。"
    ),
)
_LOGISTICS = DomainAgent(
    name="logistics",
    tool_names=["query_order", "query_logistics", "modify_address"],
    system_prompt=(
        "你是 OpenChatShop 的订单物流专家。负责订单状态查询、物流跟踪、收货地址修改。"
        "依据工具返回的真实数据，用自然、友好的中文简洁回复。"
    ),
)


def build_default_agents() -> AgentRegistry:
    """Return an AgentRegistry populated with the three default specialists."""
    registry = AgentRegistry()
    for agent in (_REFUND, _SALES, _LOGISTICS):
        registry.register(agent)
    return registry
