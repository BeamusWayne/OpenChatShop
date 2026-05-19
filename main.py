"""OpenChatShop entry point — wires all components and starts the server."""
from __future__ import annotations

import logging
from pathlib import Path

import uvicorn
from fastapi.staticfiles import StaticFiles

from open_chat_shop.api.app import create_app
from open_chat_shop.core.context import InMemoryContextManager
from open_chat_shop.core.intent import CascadeIntentEngine, RuleBasedMatcher
from open_chat_shop.core.orchestrator import DialogueOrchestrator
from open_chat_shop.core.security import SecurityGuard
from open_chat_shop.core.strategy import RuleBasedStrategy
from open_chat_shop.core.tool import ToolInjector
from open_chat_shop.core.types import RoutingRule
from open_chat_shop.tools.builtin import ALL_TOOLS

try:
    from open_chat_shop.core.anthropic_provider import AnthropicProvider
    _LLM_AVAILABLE = True
except ImportError:
    _LLM_AVAILABLE = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Default intent rules — keyword patterns for each of the 8 builtin intents.
DEFAULT_RULES: list[tuple[str, str, float]] = [
    ("query_order", r"查询订单|查订单|查看订单|看订单|order|我的订单", 1.0),
    ("query_order", r"订单[号编号]?", 0.5),
    ("query_order", r"ORD-\w+", 0.3),
    ("query_logistics", r"物流|快递|到哪了|配送|发货|运[单输]号|logistics|订单到哪", 1.5),
    ("query_logistics", r"订单.{0,4}到哪", 2.5),
    ("search_product", r"搜索|查找|找一下|有没有|想买|来[一几]个|search", 1.0),
    ("check_refund_eligibility", r"退款[条资][格格]力|能退吗|可以退|退款条件|能退款|能退吗", 2.0),
    ("create_refund", r"退款|退货|refund|退[一款货]", 1.0),
    ("cancel_order", r"取消订单|cancel", 1.5),
    ("cancel_order", r"取消|不想要了|不要了", 0.6),
    ("modify_address", r"修改?地址|换地址|地址改|改[一一下]?地址", 1.0),
    ("handoff_to_human", r"转人工|人工客服|真人|客服|转接|human|agent", 1.0),
    ("greeting", r"你好|您好|hi|hello|嗨|hey", 0.8),
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
    intent_engine = CascadeIntentEngine(rule_matcher, level1_threshold=0.60)

    # Wire LLM provider for Level 3 intent classification
    if _LLM_AVAILABLE:
        try:
            provider = AnthropicProvider()
            intent_engine.set_provider(provider)
            logger.info("LLM provider (Anthropic/GLM) connected")
        except Exception as e:
            logger.warning("LLM provider unavailable, using rules only: %s", e)

    # Instantiate tools and build registry + routing rules
    tool_registry = {}
    intent_to_tools: dict[str, list[str]] = {}
    for tool_cls in ALL_TOOLS:
        tool = tool_cls()
        tool_registry[tool.name] = tool
        intent_to_tools[tool.name] = [tool.name]

    routing_rules = [
        RoutingRule(
            intent_patterns=[name],
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
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app


app = create_main_app()

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
