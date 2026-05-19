"""Tests for BaseTool ABC and ToolInjector."""
from __future__ import annotations

import pytest

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
from commerce_agent.core.tool import BaseTool, ToolInjector


# ---------------------------------------------------------------------------
# Concrete test tool
# ---------------------------------------------------------------------------


class DummyTool(BaseTool):
    """Minimal concrete tool for unit-testing BaseTool defaults."""

    name = "dummy_tool"
    description = "A test tool"
    category = "test"
    params_schema = {
        "type": "object",
        "properties": {"input": {"type": "string"}},
        "required": ["input"],
    }
    permissions = ToolPermission(required_roles=["customer"])

    async def execute(self, params: dict, context: SessionContext) -> ToolResult:
        return ToolResult(success=True, data=params)


class AdminTool(BaseTool):
    """Tool that requires admin role."""

    name = "admin_tool"
    description = "Admin-only tool"
    category = "admin"
    params_schema = {
        "type": "object",
        "properties": {"action": {"type": "string"}},
        "required": ["action"],
    }
    permissions = ToolPermission(required_roles=["admin"])

    async def execute(self, params: dict, context: SessionContext) -> ToolResult:
        return ToolResult(success=True, data=params)


class OpenTool(BaseTool):
    """Tool with no role restriction."""

    name = "open_tool"
    description = "Open to all"
    category = "general"
    params_schema = {"type": "object", "properties": {}}
    permissions = ToolPermission(required_roles=[])

    async def execute(self, params: dict, context: SessionContext) -> ToolResult:
        return ToolResult(success=True, data={"open": True})


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def dummy_tool() -> DummyTool:
    return DummyTool()


@pytest.fixture
def context() -> SessionContext:
    return SessionContext(
        session_id="test-session",
        user_id="user-1",
        channel="web",
        user_role="customer",
    )


@pytest.fixture
def order_intent() -> Intent:
    return Intent(
        name="query_order",
        display_name="查询订单",
        confidence=0.95,
        source="rule",
    )


# ---------------------------------------------------------------------------
# BaseTool tests
# ---------------------------------------------------------------------------


class TestBaseToolABC:
    @pytest.mark.unit
    def test_cannot_instantiate_abstract(self):
        """BaseTool is abstract and must not be instantiated directly."""
        with pytest.raises(TypeError):
            BaseTool()  # type: ignore[abstract]


class TestBaseToolValidate:
    @pytest.mark.unit
    def test_valid_params(self, dummy_tool: DummyTool):
        result = dummy_tool.validate({"input": "hello"})
        assert result.valid is True
        assert result.errors == []

    @pytest.mark.unit
    def test_invalid_params_missing_required(self, dummy_tool: DummyTool):
        result = dummy_tool.validate({})
        assert result.valid is False
        assert len(result.errors) == 1
        assert "'input' is a required property" in result.errors[0]

    @pytest.mark.unit
    def test_invalid_params_wrong_type(self, dummy_tool: DummyTool):
        result = dummy_tool.validate({"input": 123})
        assert result.valid is False
        assert any("string" in e for e in result.errors)


class TestBaseToolPreCheck:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_default_pre_check_passes(
        self, dummy_tool: DummyTool, context: SessionContext
    ):
        result = await dummy_tool.pre_check({"input": "x"}, context)
        assert result.passed is True
        assert result.reason is None


class TestBaseToolCompensate:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_default_compensate_is_noop(
        self, dummy_tool: DummyTool, context: SessionContext
    ):
        # Should not raise
        await dummy_tool.compensate({"input": "x"}, context)


class TestBaseToolToDefinition:
    @pytest.mark.unit
    def test_to_definition(self, dummy_tool: DummyTool):
        defn = dummy_tool.to_definition()
        assert isinstance(defn, ToolDefinition)
        assert defn.name == "dummy_tool"
        assert defn.description == "A test tool"
        assert defn.parameters == dummy_tool.params_schema


class TestBaseToolExecute:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_execute_returns_tool_result(
        self, dummy_tool: DummyTool, context: SessionContext
    ):
        result = await dummy_tool.execute({"input": "test"}, context)
        assert isinstance(result, ToolResult)
        assert result.success is True
        assert result.data == {"input": "test"}


# ---------------------------------------------------------------------------
# ToolInjector tests
# ---------------------------------------------------------------------------


def _make_injector(
    tools: list[BaseTool] | None = None,
    rules: list[RoutingRule] | None = None,
    max_tools: int = 5,
) -> ToolInjector:
    """Build a ToolInjector with sensible defaults for testing."""
    all_tools = tools or [DummyTool(), AdminTool(), OpenTool()]
    registry = {t.name: t for t in all_tools}
    if rules is None:
        rules = [
            RoutingRule(
                intent_patterns=["query_*"],
                scenario=None,
                tools=["dummy_tool", "open_tool"],
                priority=1,
            ),
            RoutingRule(
                intent_patterns=["admin_*"],
                scenario=None,
                tools=["admin_tool"],
                priority=2,
            ),
            RoutingRule(
                intent_patterns=["*"],
                scenario="refund",
                tools=["dummy_tool"],
                priority=0,
            ),
        ]
    return ToolInjector(
        registry=registry, routing_rules=rules, max_tools_per_turn=max_tools
    )


class TestToolInjectorIntentMatch:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_returns_tools_matching_intent_pattern(
        self, context: SessionContext
    ):
        injector = _make_injector()
        intent = Intent(
            name="query_order", display_name="Query", confidence=0.9, source="rule"
        )
        tools = await injector.inject(intent, context)
        names = [t.name for t in tools]
        assert "dummy_tool" in names
        assert "open_tool" in names
        assert "admin_tool" not in names

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_wildcard_pattern_matches_any_intent(self, context: SessionContext):
        injector = _make_injector(
            rules=[
                RoutingRule(
                    intent_patterns=["*"],
                    scenario=None,
                    tools=["open_tool"],
                    priority=0,
                ),
            ],
        )
        intent = Intent(
            name="anything_at_all", display_name="X", confidence=0.5, source="llm"
        )
        tools = await injector.inject(intent, context)
        assert len(tools) == 1
        assert tools[0].name == "open_tool"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_unmatched_intent_returns_empty(self, context: SessionContext):
        injector = _make_injector(
            rules=[
                RoutingRule(
                    intent_patterns=["query_*"],
                    scenario=None,
                    tools=["dummy_tool"],
                    priority=1,
                ),
            ],
        )
        intent = Intent(
            name="refund_request",
            display_name="Refund",
            confidence=0.8,
            source="semantic",
        )
        tools = await injector.inject(intent, context)
        assert tools == []


class TestToolInjectorScenarioFilter:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_filters_by_scenario(self):
        ctx = SessionContext(
            session_id="s1",
            user_id="u1",
            channel="web",
            user_role="customer",
            current_scenario="refund",
        )
        injector = _make_injector()
        intent = Intent(
            name="query_order", display_name="Query", confidence=0.9, source="rule"
        )
        tools = await injector.inject(intent, ctx)
        # refund scenario rule only includes dummy_tool
        names = [t.name for t in tools]
        assert "dummy_tool" in names
        assert "open_tool" not in names

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_no_scenario_in_context_keeps_all(self, context: SessionContext):
        injector = _make_injector()
        intent = Intent(
            name="query_order", display_name="Query", confidence=0.9, source="rule"
        )
        tools = await injector.inject(intent, context)
        # context.current_scenario is None, so scenario filter is skipped
        names = [t.name for t in tools]
        assert "dummy_tool" in names
        assert "open_tool" in names


class TestToolInjectorPermissionFilter:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_filters_by_role(self):
        ctx = SessionContext(
            session_id="s1",
            user_id="u1",
            channel="web",
            user_role="customer",
        )
        injector = _make_injector()
        intent = Intent(
            name="admin_action", display_name="Admin", confidence=0.9, source="rule"
        )
        tools = await injector.inject(intent, ctx)
        # admin_tool requires "admin" role, customer cannot access
        names = [t.name for t in tools]
        assert "admin_tool" not in names

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_admin_role_gets_admin_tool(self):
        ctx = SessionContext(
            session_id="s1",
            user_id="u1",
            channel="web",
            user_role="admin",
        )
        injector = _make_injector()
        intent = Intent(
            name="admin_action", display_name="Admin", confidence=0.9, source="rule"
        )
        tools = await injector.inject(intent, ctx)
        names = [t.name for t in tools]
        assert "admin_tool" in names

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_wildcard_role_allows_any_role(self):
        wildcard_tool = type(
            "WildcardTool",
            (BaseTool,),
            {
                "name": "wildcard_tool",
                "description": "Wildcard",
                "category": "general",
                "params_schema": {"type": "object", "properties": {}},
                "permissions": ToolPermission(required_roles=["*"]),
                "execute": lambda self, params, ctx: ToolResult(success=True),
            },
        )()
        injector = _make_injector(
            tools=[wildcard_tool],
            rules=[
                RoutingRule(
                    intent_patterns=["test_*"],
                    scenario=None,
                    tools=["wildcard_tool"],
                    priority=1,
                ),
            ],
        )
        ctx = SessionContext(
            session_id="s1", user_id="u1", channel="web", user_role="guest"
        )
        intent = Intent(
            name="test_something",
            display_name="Test",
            confidence=0.9,
            source="rule",
        )
        tools = await injector.inject(intent, ctx)
        assert len(tools) == 1
        assert tools[0].name == "wildcard_tool"


class TestToolInjectorQuantityTruncation:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_truncates_to_max_tools(self, context: SessionContext):
        injector = _make_injector(max_tools=1)
        intent = Intent(
            name="query_order", display_name="Query", confidence=0.9, source="rule"
        )
        tools = await injector.inject(intent, context)
        assert len(tools) <= 1


class TestToolInjectorDefinitions:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_inject_definitions_returns_tool_definitions(
        self, context: SessionContext
    ):
        injector = _make_injector()
        intent = Intent(
            name="query_order", display_name="Query", confidence=0.9, source="rule"
        )
        definitions = await injector.inject_definitions(intent, context)
        assert all(isinstance(d, ToolDefinition) for d in definitions)
        assert len(definitions) > 0


class TestToolInjectorRegistry:
    @pytest.mark.unit
    def test_get_tool_returns_tool(self):
        dummy = DummyTool()
        injector = _make_injector(tools=[dummy], rules=[])
        assert injector.get_tool("dummy_tool") is dummy

    @pytest.mark.unit
    def test_get_tool_returns_none_for_unknown(self):
        injector = _make_injector(rules=[])
        assert injector.get_tool("nonexistent") is None

    @pytest.mark.unit
    def test_register_adds_tool(self):
        injector = _make_injector(rules=[])
        new_tool = DummyTool()
        new_tool.name = "new_tool"  # type: ignore[mutable-class-default]
        injector.register(new_tool)
        assert injector.get_tool("new_tool") is new_tool
