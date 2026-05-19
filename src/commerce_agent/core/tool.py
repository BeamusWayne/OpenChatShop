"""Tool system core: BaseTool ABC and ToolInjector.

Implements contracts.md sections 4-5:
  - BaseTool: abstract base with validate/pre_check/execute/compensate lifecycle
  - ToolInjector: 4-layer dynamic tool injection (intent -> scenario -> permission -> quantity)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
import fnmatch
import logging
from typing import Any

import jsonschema

from commerce_agent.core.types import (
    CheckResult,
    Intent,
    RoutingRule,
    SessionContext,
    ToolDefinition,
    ToolPermission,
    ToolResult,
    ValidationResult,
)
from commerce_agent.core.exceptions import ToolError

logger = logging.getLogger(__name__)


class BaseTool(ABC):
    """Abstract base class for all tools.

    Subclasses must define class-level attributes (name, description,
    params_schema, permissions) and implement the ``execute`` method.
    """

    name: str
    description: str
    category: str = "general"
    params_schema: dict[str, Any]
    permissions: ToolPermission

    @abstractmethod
    async def execute(self, params: dict, context: SessionContext) -> ToolResult:
        """Execute tool logic.  Subclasses MUST implement."""

    # ------------------------------------------------------------------
    # Lifecycle hooks with sensible defaults
    # ------------------------------------------------------------------

    def validate(self, params: dict) -> ValidationResult:
        """Validate *params* against the tool's JSON Schema."""
        try:
            jsonschema.validate(params, self.params_schema)
            return ValidationResult(valid=True)
        except jsonschema.ValidationError as exc:
            return ValidationResult(valid=False, errors=[exc.message])

    async def pre_check(self, params: dict, context: SessionContext) -> CheckResult:
        """Business pre-check.  Default: always passes."""
        return CheckResult(passed=True)

    async def compensate(self, params: dict, context: SessionContext) -> None:
        """Compensation logic for failed writes.  Default: no-op."""

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def to_definition(self) -> ToolDefinition:
        """Return a :class:`ToolDefinition` suitable for LLM consumption."""
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters=self.params_schema,
        )


class ToolInjector:
    """Dynamic tool injection based on intent.

    4-layer filtering pipeline:
      1. Intent match  (glob patterns against routing rules)
      2. Scenario filter
      3. Permission filter (RBAC)
      4. Quantity truncation
    """

    def __init__(
        self,
        registry: dict[str, BaseTool],
        routing_rules: list[RoutingRule],
        max_tools_per_turn: int = 5,
    ) -> None:
        self._registry = registry
        self._routing_rules = sorted(
            routing_rules, key=lambda r: r.priority, reverse=True
        )
        self._max_tools = max_tools_per_turn

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def inject(self, intent: Intent, context: SessionContext) -> list[BaseTool]:
        """Run the full 4-layer filter chain and return matching tools."""
        # Layer 1 — intent matching
        candidate_tools = self._match_intent(intent.name)
        if not candidate_tools:
            logger.warning("No tools matched intent", extra={"intent": intent.name})
            return []

        # Layer 2 — scenario filtering
        if context.current_scenario:
            candidate_tools = self._filter_scenario(
                candidate_tools, context.current_scenario
            )

        # Layer 3 — permission filtering
        candidate_tools = self._filter_permissions(candidate_tools, context.user_role)

        # Layer 4 — quantity truncation
        candidate_tools = candidate_tools[: self._max_tools]

        logger.info(
            "Tool injection complete",
            extra={"intent": intent.name, "tools": [t.name for t in candidate_tools]},
        )
        return candidate_tools

    async def inject_definitions(
        self, intent: Intent, context: SessionContext
    ) -> list[ToolDefinition]:
        """Convenience wrapper: inject tools, then return their definitions."""
        tools = await self.inject(intent, context)
        return [t.to_definition() for t in tools]

    # ------------------------------------------------------------------
    # Registry helpers
    # ------------------------------------------------------------------

    def get_tool(self, name: str) -> BaseTool | None:
        """Look up a tool by name from the registry."""
        return self._registry.get(name)

    def register(self, tool: BaseTool) -> None:
        """Add (or replace) a tool in the registry."""
        self._registry[tool.name] = tool

    # ------------------------------------------------------------------
    # Private filter layers
    # ------------------------------------------------------------------

    def _match_intent(self, intent_name: str) -> list[BaseTool]:
        """Match intent against routing rules using glob patterns."""
        tool_names: list[str] = []
        for rule in self._routing_rules:
            for pattern in rule.intent_patterns:
                if fnmatch.fnmatch(intent_name, pattern):
                    tool_names.extend(rule.tools)

        # Deduplicate while preserving insertion order
        seen: set[str] = set()
        result: list[BaseTool] = []
        for name in tool_names:
            if name not in seen and name in self._registry:
                seen.add(name)
                result.append(self._registry[name])
        return result

    def _filter_scenario(
        self, tools: list[BaseTool], scenario: str
    ) -> list[BaseTool]:
        """Keep only tools that belong to the current scenario.

        If no routing rules mention the given scenario the list is
        returned unchanged (permissive fallback).
        """
        scenario_tools: set[str] = set()
        has_scenario_rules = False
        for rule in self._routing_rules:
            if rule.scenario == scenario:
                has_scenario_rules = True
                scenario_tools.update(rule.tools)

        if not has_scenario_rules:
            return tools
        return [t for t in tools if t.name in scenario_tools]

    def _filter_permissions(
        self, tools: list[BaseTool], role: str
    ) -> list[BaseTool]:
        """Keep only tools whose ``required_roles`` allow *role*."""
        result: list[BaseTool] = []
        for tool in tools:
            if not tool.permissions.required_roles:
                result.append(tool)
            elif (
                role in tool.permissions.required_roles
                or "*" in tool.permissions.required_roles
            ):
                result.append(tool)
        return result
