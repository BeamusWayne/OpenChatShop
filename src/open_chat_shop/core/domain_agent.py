"""Domain agents — the Multi-Agent foundation (V2.0 module 1, feat-048).

Instead of one monolithic orchestrator carrying every tool and a single global
prompt, the Multi-Agent design splits work across ``DomainAgent`` specialists
(refund / sales / logistics …). Each agent declares only the tool *names* it
owns and a domain-specific system prompt, so a sales agent never sees the refund
API and prompts stay small.

This module is the additive foundation: the ``DomainAgent`` value object and the
``AgentRegistry``. Execution (a ``handle()`` that actually runs a turn) and the
orchestrator wiring are deferred to feat-051, where the feature-flagged
integration and its fallback live — so nothing here touches the existing flow.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, TypeVar


class _NamedTool(Protocol):
    """Anything with a ``name`` — e.g. a ``BaseTool`` — can be scoped."""

    name: str


_ToolT = TypeVar("_ToolT", bound=_NamedTool)


class DomainAgent:
    """A specialist that owns a named subset of tools and its own prompt.

    Carries no execution logic by design (feat-048): it is the declaration of
    *which* tools belong to a domain plus the domain's system prompt. feat-051
    decides how an agent runs a turn.
    """

    def __init__(
        self,
        name: str,
        tool_names: Iterable[str],
        system_prompt: str,
    ) -> None:
        self.name = name
        self.tool_names: frozenset[str] = frozenset(tool_names)
        self.system_prompt = system_prompt

    def allows_tool(self, tool_name: str) -> bool:
        """Return True if *tool_name* belongs to this domain."""
        return tool_name in self.tool_names

    def scope_tools(self, tools: Iterable[_ToolT]) -> list[_ToolT]:
        """Return a new list of *tools* restricted to this domain (by name).

        Does not mutate the input; preserves the input order.
        """
        return [tool for tool in tools if tool.name in self.tool_names]


class AgentRegistry:
    """Registry of domain agents, keyed by domain name."""

    def __init__(self) -> None:
        self._agents: dict[str, DomainAgent] = {}

    def register(self, agent: DomainAgent) -> None:
        """Register *agent* under its domain name (re-registering replaces)."""
        self._agents[agent.name] = agent

    def get(self, name: str) -> DomainAgent | None:
        """Return the agent for domain *name*, or None if not registered."""
        return self._agents.get(name)

    @property
    def domains(self) -> list[str]:
        """Sorted list of registered domain names."""
        return sorted(self._agents)

    def route_tool(self, tool_name: str) -> DomainAgent | None:
        """Return the registered agent that owns *tool_name*, or None.

        Resolution is deterministic (domains checked in sorted order) so a tool
        shared by more than one domain always routes the same way.
        """
        for name in sorted(self._agents):
            if self._agents[name].allows_tool(tool_name):
                return self._agents[name]
        return None
