"""OpenChatShop entry point — wires all components and starts the server."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import uvicorn
from fastapi.staticfiles import StaticFiles

from open_chat_shop.api.app import create_app
from open_chat_shop.core.context import InMemoryContextManager
from open_chat_shop.core.handoff import HandoffQueue
from open_chat_shop.core.intent import CascadeIntentEngine, RuleBasedMatcher
from open_chat_shop.core.orchestrator import DialogueOrchestrator
from open_chat_shop.core.scenario import RefundScenarioFSM
from open_chat_shop.core.scenarios.complaint import ComplaintScenarioFSM
from open_chat_shop.core.scenarios.order_inquiry import OrderInquiryScenarioFSM
from open_chat_shop.core.security import SecurityGuard
from open_chat_shop.core.strategy import RuleBasedStrategy
from open_chat_shop.core.tool import ToolInjector
from open_chat_shop.core.tool_response_mapper import ToolResponseMapper
from open_chat_shop.core.types import IntentInfo, RoutingRule
from open_chat_shop.observability.logging import setup_logging
from open_chat_shop.tools.builtin import ALL_TOOLS

from open_chat_shop.core.middleware import (
    MiddlewarePipeline,
    RateLimitMiddleware,
    BudgetMiddleware,
    SlotTrackingMiddleware,
)
from open_chat_shop.core.rate_limiter import InMemoryRateLimiter, RateLimitGuard
from open_chat_shop.core.cost_governance import SessionBudgetManager, BudgetConfig
from open_chat_shop.core.slot_tracker import create_builtin_tracker

try:
    from open_chat_shop.core.anthropic_provider import AnthropicProvider
    _LLM_AVAILABLE = True
except ImportError:
    _LLM_AVAILABLE = False

# Structured logging (replaces basicConfig)
setup_logging(level="INFO")
logger = logging.getLogger(__name__)

# OpenTelemetry tracing — safe no-op if packages are missing
try:
    from open_chat_shop.observability.tracing import setup_tracing
    setup_tracing(service_name="open-chat-shop")
except Exception:
    logger.warning("OpenTelemetry tracing not available, continuing without tracing")

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
    ("thanks", r"谢谢|感谢|多谢|thanks|thank you|thx", 0.8),
]


def _register_default_rules(matcher: RuleBasedMatcher) -> None:
    for intent_name, pattern, weight in DEFAULT_RULES:
        matcher.add_rule(intent_name, pattern, weight)


def _build_context_manager() -> Any:
    """Select context manager based on environment variables.

    Priority: DATABASE_URL > REDIS_URL > InMemoryContextManager.
    Falls back gracefully when the chosen backend is unavailable.
    """
    _database_url = os.environ.get("DATABASE_URL", "")
    _redis_url = os.environ.get("REDIS_URL", "")

    if _database_url:
        try:
            from open_chat_shop.storage.db_context import DatabaseContextManager
            context_manager = DatabaseContextManager(_database_url)
            safe_url = _database_url.split("@")[-1] if "@" in _database_url else "sqlite"
            logger.info("Using database context manager (%s)", safe_url)
            return context_manager
        except Exception as e:
            logger.warning("Database context manager failed, falling back to memory: %s", e)

    if _redis_url:
        try:
            import redis.asyncio as aioredis
            from open_chat_shop.storage.redis_context import RedisContextManager
            redis_client = aioredis.from_url(_redis_url)
            context_manager = RedisContextManager(redis_client)
            logger.info("Using Redis context manager")
            return context_manager
        except Exception as e:
            logger.warning("Redis context manager failed, falling back to memory: %s", e)

    logger.info("Using in-memory context manager")
    return InMemoryContextManager()


def _build_provider() -> Any:
    """Try Anthropic provider first, then LiteLLM, then return None."""
    if _LLM_AVAILABLE:
        try:
            provider = AnthropicProvider()
            logger.info("LLM provider (Anthropic/GLM) connected")
            return provider
        except Exception as e:
            logger.warning("Anthropic provider unavailable: %s", e)

    try:
        from open_chat_shop.core.litellm_provider import LiteLLMProvider
        provider = LiteLLMProvider(model="gpt-4o-mini")
        logger.info("LLM provider (LiteLLM) connected")
        return provider
    except Exception as e:
        logger.warning("LiteLLM provider unavailable, using rules only: %s", e)

    return None


def build_orchestrator() -> DialogueOrchestrator:
    """Construct the full component pipeline and return a DialogueOrchestrator."""
    security_config: dict = {"rbac": {}}
    security_guard = SecurityGuard(security_config)

    # Task 1: Smart storage selection based on environment
    context_manager = _build_context_manager()

    rule_matcher = RuleBasedMatcher()
    _register_default_rules(rule_matcher)
    intent_engine = CascadeIntentEngine(rule_matcher, level1_threshold=0.85)

    # Register all supported intents so Level-3 LLM knows what is available
    INTENT_DEFINITIONS = [
        IntentInfo(name="query_order", display_name="查询订单", description="用户想查询订单状态、详情", sample_count=3, typical_entities=["order_id"]),
        IntentInfo(name="query_logistics", display_name="物流查询", description="用户想查询快递物流状态", sample_count=4, typical_entities=["order_id"]),
        IntentInfo(name="search_product", display_name="搜索商品", description="用户想搜索或浏览商品", sample_count=4, typical_entities=["keyword", "category"]),
        IntentInfo(name="check_refund_eligibility", display_name="查看退款条件", description="用户想知道订单能否退款", sample_count=3, typical_entities=["order_id"]),
        IntentInfo(name="create_refund", display_name="申请退款", description="用户想申请退款或退货", sample_count=2, typical_entities=["order_id", "reason"]),
        IntentInfo(name="cancel_order", display_name="取消订单", description="用户想取消订单", sample_count=2, typical_entities=["order_id", "reason"]),
        IntentInfo(name="modify_address", display_name="修改地址", description="用户想修改收货地址", sample_count=2, typical_entities=["order_id", "new_address"]),
        IntentInfo(name="handoff_to_human", display_name="转人工客服", description="用户想转接人工客服", sample_count=2, typical_entities=[]),
        IntentInfo(name="greeting", display_name="打招呼", description="用户打招呼", sample_count=2, typical_entities=[]),
        IntentInfo(name="thanks", display_name="感谢", description="用户表示感谢", sample_count=2, typical_entities=[]),
    ]

    for info in INTENT_DEFINITIONS:
        intent_engine.register_intent(info)

    # Task 3: Load intent samples for Level-2 semantic matching
    try:
        from open_chat_shop.evaluation.golden_dataset import BUILT_IN_SAMPLES
        # add_samples() is async but purely synchronous internally (dict append),
        # so we populate the internal dict directly during startup.
        for sample in BUILT_IN_SAMPLES:
            intent_name = sample.expected_intent
            if intent_name not in intent_engine._samples:
                intent_engine._samples[intent_name] = []
            intent_engine._samples[intent_name].append(sample.user_input)
        logger.info("Loaded %d intent samples for semantic matching", len(BUILT_IN_SAMPLES))
    except Exception as e:
        logger.warning("Could not load intent samples: %s", e)

    # Task 2: Wire LLM provider (Anthropic -> LiteLLM fallback)
    provider = _build_provider()
    if provider is not None:
        intent_engine.set_provider(provider)

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

    orchestrator = DialogueOrchestrator(
        security_guard=security_guard,
        context_manager=context_manager,
        intent_engine=intent_engine,
        tool_injector=tool_injector,
        strategy=strategy,
    )

    if provider is not None:
        try:
            orchestrator.set_provider(provider)
        except Exception:
            pass

    # Wire observability: audit logger and cost tracker
    try:
        from open_chat_shop.observability.logging import AuditLogger, CostTracker
        orchestrator.set_audit_logger(AuditLogger())
        orchestrator.set_cost_tracker(CostTracker())
    except Exception:
        logger.warning("Observability wiring failed, continuing without audit/cost tracking")

    # Wire ToolResponseMapper for rich tool-result messages
    orchestrator.set_tool_response_mapper(ToolResponseMapper())

    # Wire scenario FSMs for multi-turn business dialogue flows
    scenarios = {
        "refund": RefundScenarioFSM(),
        "complaint": ComplaintScenarioFSM(),
        "order_inquiry": OrderInquiryScenarioFSM(),
    }
    orchestrator.set_scenarios(scenarios)

    # Wire HandoffQueue for human-agent transfer tracking
    handoff_queue = HandoffQueue()
    orchestrator.set_handoff_queue(handoff_queue)

    # Wire middleware pipeline: rate limiting -> budget enforcement -> slot tracking
    rate_limiter = InMemoryRateLimiter()
    rate_guard = RateLimitGuard(rate_limiter)
    budget_manager = SessionBudgetManager(BudgetConfig(max_tokens=100_000))
    slot_tracker = create_builtin_tracker()

    pipeline = MiddlewarePipeline()
    pipeline.add(RateLimitMiddleware(rate_guard))
    pipeline.add(BudgetMiddleware(budget_manager))
    pipeline.add(SlotTrackingMiddleware(slot_tracker))
    orchestrator.set_middleware_pipeline(pipeline)

    return orchestrator


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
