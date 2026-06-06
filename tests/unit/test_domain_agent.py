"""Tests for DomainAgent + AgentRegistry (Multi-Agent foundation, feat-048).

feat-048 delivers the additive data structure + registry only: a DomainAgent
carries a domain name, its scoped tool-name set, and a system prompt; the
AgentRegistry registers them and routes a tool to its owning agent. Execution
(handle()) and orchestrator integration are deferred to feat-051 by design, so
this layer touches no existing flow.
"""
from __future__ import annotations

import pytest

from open_chat_shop.core.domain_agent import AgentRegistry, DomainAgent


class _StubTool:
    """Minimal tool stand-in: scope_tools only needs ``.name``."""

    def __init__(self, name: str) -> None:
        self.name = name


@pytest.fixture()
def refund_agent() -> DomainAgent:
    return DomainAgent(
        name="refund",
        tool_names=["check_refund_eligibility", "create_refund", "cancel_order"],
        system_prompt="你是售后退款专家。",
    )


@pytest.mark.unit
class TestDomainAgent:
    def test_allows_tool_in_domain(self, refund_agent: DomainAgent) -> None:
        assert refund_agent.allows_tool("create_refund") is True

    def test_rejects_tool_outside_domain(self, refund_agent: DomainAgent) -> None:
        # A refund agent must not know about search_product (导购专家的工具) —
        # that scoping is the whole point of the Multi-Agent split.
        assert refund_agent.allows_tool("search_product") is False

    def test_scope_tools_filters_to_domain(self, refund_agent: DomainAgent) -> None:
        tools = [
            _StubTool("create_refund"),
            _StubTool("search_product"),
            _StubTool("cancel_order"),
        ]
        scoped = refund_agent.scope_tools(tools)
        assert [t.name for t in scoped] == ["create_refund", "cancel_order"]

    def test_scope_tools_does_not_mutate_input(self, refund_agent: DomainAgent) -> None:
        tools = [_StubTool("create_refund"), _StubTool("search_product")]
        refund_agent.scope_tools(tools)
        assert [t.name for t in tools] == ["create_refund", "search_product"]

    def test_exposes_system_prompt(self, refund_agent: DomainAgent) -> None:
        assert refund_agent.system_prompt == "你是售后退款专家。"

    def test_empty_domain_allows_nothing(self) -> None:
        # Boundary: an agent with no tools owns nothing and scopes to empty.
        agent = DomainAgent("empty", [], "占位")
        assert agent.allows_tool("create_refund") is False
        assert agent.scope_tools([_StubTool("create_refund")]) == []


@pytest.mark.unit
class TestAgentRegistry:
    def test_register_and_get(self, refund_agent: DomainAgent) -> None:
        reg = AgentRegistry()
        reg.register(refund_agent)
        assert reg.get("refund") is refund_agent

    def test_get_unknown_domain_returns_none(self) -> None:
        assert AgentRegistry().get("nope") is None

    def test_domains_sorted(self, refund_agent: DomainAgent) -> None:
        reg = AgentRegistry()
        reg.register(DomainAgent("sales", ["search_product"], "导购"))
        reg.register(refund_agent)
        assert reg.domains == ["refund", "sales"]

    def test_route_tool_to_owning_agent(self, refund_agent: DomainAgent) -> None:
        reg = AgentRegistry()
        reg.register(refund_agent)
        reg.register(DomainAgent("logistics", ["query_logistics"], "物流"))
        assert reg.route_tool("query_logistics").name == "logistics"  # type: ignore[union-attr]
        assert reg.route_tool("create_refund").name == "refund"  # type: ignore[union-attr]

    def test_route_unknown_tool_returns_none(self, refund_agent: DomainAgent) -> None:
        reg = AgentRegistry()
        reg.register(refund_agent)
        assert reg.route_tool("nonexistent_tool") is None

    def test_route_tool_shared_by_domains_is_deterministic(self) -> None:
        # handoff_to_human is plausibly shared; routing must be stable, not
        # dict-insertion-order dependent. Sorted order -> "general" before "zzz".
        reg = AgentRegistry()
        reg.register(DomainAgent("zzz", ["handoff_to_human"], "z"))
        reg.register(DomainAgent("general", ["handoff_to_human"], "g"))
        assert reg.route_tool("handoff_to_human").name == "general"  # type: ignore[union-attr]
