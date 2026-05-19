"""CommerceAgent entry point — wires all components and starts the server."""
from __future__ import annotations

import logging
from pathlib import Path

import uvicorn
from fastapi.staticfiles import StaticFiles

from commerce_agent.api.app import create_app
from commerce_agent.core.context import InMemoryContextManager
from commerce_agent.core.intent import CascadeIntentEngine, RuleBasedMatcher
from commerce_agent.core.orchestrator import DialogueOrchestrator
from commerce_agent.core.security import SecurityGuard
from commerce_agent.core.strategy import RuleBasedStrategy
from commerce_agent.core.tool import ToolInjector
from commerce_agent.core.types import RoutingRule
from commerce_agent.tools.builtin import ALL_TOOLS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Default intent rules — keyword patterns for each of the 8 builtin intents.
DEFAULT_RULES: list[tuple[str, str, float]] = [
    ("query_order", r"查询?订单|查订单|订单[号编号]?|order|我的订单", 1.0),
    ("query_order", r"ORD-\w+", 0.9),
    ("query_logistics", r"物流|快递|到哪了|配送|发货|运[单输]号|logistics", 1.0),
    ("search_product", r"搜索?|查找?|找一下|有没有|想买|来[一几]个|search", 1.0),
    ("check_refund_eligibility", r"退款[条资][格格]力|能退吗|可以退|退款条件|能退款", 1.0),
    ("create_refund", r"退款|退货|refund|退[一款货]", 1.0),
    ("cancel_order", r"取消订单|取消|cancel|不想要了|不要了", 1.0),
    ("modify_address", r"修改?地址|换地址|地址改|改[一一下]?地址", 1.0),
    ("handoff_to_human", r"转人工|人工客服|真人|客服|转接|human|agent", 1.0),
]


def _register_default_rules(matcher: RuleBasedMatcher) -> None:
    for intent_name, pattern, weight in DEFAULT_RULES:
        matcher.add_rule(intent_name, pattern, weight)


def build_orchestrator() -> DialogueOrchestrator:
    """Construct the full component pipeline and return a DialogueOrchestrator."""
    security_config: dict = {"rbac": {}}
    security_guard = SecurityGuard(security_config)

    context_manager = InMemoryContextManager()

    rule_matcher = RuleBasedMatcher()
    _register_default_rules(rule_matcher)
    intent_engine = CascadeIntentEngine(rule_matcher)

    # Instantiate tools and build registry + routing rules
    tool_registry = {}
    intent_to_tools: dict[str, list[str]] = {}
    for tool_cls in ALL_TOOLS:
        tool = tool_cls()
        tool_registry[tool.name] = tool
        intent_to_tools[tool.name] = [tool.name]

    routing_rules = [
        RoutingRule(
            intent_patterns=[name, "*"],
            tools=tool_names,
            priority=10 if len(tool_names) == 1 else 0,
        )
        for name, tool_names in intent_to_tools.items()
    ]

    tool_injector = ToolInjector(
        registry=tool_registry,
        routing_rules=routing_rules,
    )

    strategy = RuleBasedStrategy()

    return DialogueOrchestrator(
        security_guard=security_guard,
        context_manager=context_manager,
        intent_engine=intent_engine,
        tool_injector=tool_injector,
        strategy=strategy,
    )


def create_main_app():
    """Build the app with orchestrator wired in and static files mounted."""
    orchestrator = build_orchestrator()
    app = create_app(orchestrator)

    static_dir = Path(__file__).parent / "static"
    if static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/")
    async def root():
        return {"message": "CommerceAgent is running", "version": "0.1.0"}

    return app


app = create_main_app()

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
