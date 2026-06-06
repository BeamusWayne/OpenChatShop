"""Tests for the default domain specialists (feat-050).

build_default_agents() wires up the three V2.0 specialists — refund / sales /
logistics — each carrying only its own tools and prompt. The point of the split
is isolation: the sales agent must not know the refund API, etc.
"""
from __future__ import annotations

import pytest

from open_chat_shop.core.domain_agents import build_default_agents


@pytest.fixture()
def registry():
    return build_default_agents()


@pytest.mark.unit
class TestDefaultDomainAgents:
    def test_three_specialists_registered(self, registry) -> None:
        assert registry.domains == ["logistics", "refund", "sales"]

    def test_refund_owns_refund_tools(self, registry) -> None:
        refund = registry.get("refund")
        assert refund.allows_tool("create_refund")
        assert refund.allows_tool("check_refund_eligibility")
        assert refund.allows_tool("cancel_order")

    def test_sales_is_isolated_from_refund(self, registry) -> None:
        # The whole reason for the split: a sales agent must not see refund tools.
        sales = registry.get("sales")
        assert sales.allows_tool("search_product")
        assert sales.allows_tool("create_refund") is False
        assert sales.allows_tool("query_logistics") is False

    def test_logistics_owns_order_and_delivery_tools(self, registry) -> None:
        logistics = registry.get("logistics")
        assert logistics.allows_tool("query_order")
        assert logistics.allows_tool("query_logistics")
        assert logistics.allows_tool("modify_address")

    def test_registry_routes_each_tool_to_its_domain(self, registry) -> None:
        assert registry.route_tool("create_refund").name == "refund"
        assert registry.route_tool("search_product").name == "sales"
        assert registry.route_tool("query_logistics").name == "logistics"
        assert registry.route_tool("modify_address").name == "logistics"

    def test_handoff_is_not_a_domain_tool(self, registry) -> None:
        # handoff_to_human is Triage's escalation exit, not a specialist's tool.
        assert registry.route_tool("handoff_to_human") is None

    def test_every_specialist_has_a_prompt(self, registry) -> None:
        for domain in registry.domains:
            assert registry.get(domain).system_prompt.strip()
