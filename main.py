"""OpenChatShop entry point — wires all components and starts the server."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import uvicorn
from dotenv import load_dotenv
from fastapi.staticfiles import StaticFiles

load_dotenv()

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
from open_chat_shop.core.middleware import (
    MiddlewarePipeline,
    RateLimitMiddleware,
    BudgetMiddleware,
    SlotTrackingMiddleware,
)
from open_chat_shop.core.rate_limiter import InMemoryRateLimiter, RateLimitGuard
from open_chat_shop.core.cost_governance import SessionBudgetManager, BudgetConfig
from open_chat_shop.core.slot_tracker import create_builtin_tracker
from open_chat_shop.core.resilience import CircuitBreaker, RetryPolicy
from open_chat_shop.core.cache import ResponseCache

try:
    from open_chat_shop.core.anthropic_provider import AnthropicProvider
    _LLM_AVAILABLE = True
except ImportError:
    _LLM_AVAILABLE = False

# Structured logging (replaces basicConfig)
setup_logging(level=os.environ.get("LOG_LEVEL", "INFO"))
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


def _build_repositories() -> dict[str, Any]:
    """Select repository backend based on DATABASE_URL env var.

    Returns a dict with keys: order, product, logistics, refund, handoff.
    Falls back to in-memory repositories when the database is unavailable.
    """
    db_url = os.environ.get("DATABASE_URL", "")
    if db_url:
        try:
            from open_chat_shop.storage.database import init_db
            from open_chat_shop.storage.repositories.database import (
                DatabaseLogisticsRepository,
                DatabaseOrderRepository,
                DatabaseProductRepository,
                DatabaseRefundRepository,
            )
            from open_chat_shop.storage.repositories.memory import (
                InMemoryHandoffRepository,
            )
            from open_chat_shop.storage.repositories.seeding import seed_if_empty

            engine = init_db(db_url)
            seed_if_empty(engine)
            logger.info("Using database repositories")
            return {
                "order": DatabaseOrderRepository(engine),
                "product": DatabaseProductRepository(engine),
                "logistics": DatabaseLogisticsRepository(engine),
                "refund": DatabaseRefundRepository(engine),
                "handoff": InMemoryHandoffRepository(),
            }
        except Exception as e:
            logger.warning(
                "Database repositories failed, falling back to memory: %s", e
            )

    from open_chat_shop.storage.repositories.memory import (
        create_in_memory_repositories,
    )

    return create_in_memory_repositories()


def _load_yaml_config() -> dict:
    """Load YAML config files from configs/ directory if available."""
    config_dir = Path(__file__).parent / "configs"
    if not config_dir.is_dir():
        logger.info("No configs/ directory found, using hardcoded defaults")
        return {}

    try:
        from open_chat_shop.core.config import ConfigLoader
        config = ConfigLoader.load_all(str(config_dir))
        logger.info("Loaded YAML config from %s", config_dir)
        return config
    except FileNotFoundError as e:
        logger.warning("Config file missing (%s), using defaults for missing files", e)
        return {}
    except Exception as e:
        logger.warning("Config loading failed (%s), using hardcoded defaults", e)
        return {}


def build_orchestrator() -> DialogueOrchestrator:
    """Construct the full component pipeline and return a DialogueOrchestrator."""
    yaml_config = _load_yaml_config()

    # Build security config from YAML or fallback to empty defaults
    security_config: dict = {"rbac": {}}
    if "security" in yaml_config:
        sec = yaml_config["security"]
        security_config["injection_detection"] = {
            "enabled": sec.injection_detection.enabled,
            "max_input_length": sec.injection_detection.max_input_length,
        }
        security_config["content_safety"] = {
            "enabled": sec.content_safety.enabled,
            "pii_masking": sec.content_safety.pii_masking,
        }
        security_config["rbac"] = {
            role.name: {"tools": role.tools} for role in sec.rbac.roles
        }

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

    # Instantiate tools and build registry
    from open_chat_shop.tools.builtin import create_tools

    repos = _build_repositories()
    tool_registry = {}
    for tool in create_tools(repos):
        tool_registry[tool.name] = tool

    # Build routing rules from YAML config or fallback to per-tool defaults
    if "tool_routing" in yaml_config:
        tr = yaml_config["tool_routing"]
        routing_rules = [
            RoutingRule(
                intent_patterns=rule.intent_patterns,
                tools=rule.tools,
                priority=rule.priority,
                scenario=rule.scenario,
            )
            for rule in tr.rules
        ]
        max_tools = tr.max_tools_per_turn
    else:
        routing_rules = [
            RoutingRule(
                intent_patterns=[name],
                tools=[name],
                priority=10,
            )
            for name in tool_registry
        ]
        max_tools = 5

    tool_injector = ToolInjector(
        registry=tool_registry,
        routing_rules=routing_rules,
        max_tools_per_turn=max_tools,
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
            # Wrap provider with circuit breaker and retry for resilience
            circuit_breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=30.0)
            retry_policy = RetryPolicy(max_retries=3)
            original_generate = provider.generate

            async def _resilient_generate(*args, **kwargs):
                async def _call():
                    return await original_generate(*args, **kwargs)
                return await retry_policy.execute(circuit_breaker.call, _call)

            provider.generate = _resilient_generate
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
    _redis_url = os.environ.get("REDIS_URL", "")
    redis_client = None
    if _redis_url:
        try:
            import redis.asyncio as aioredis
            redis_client = aioredis.from_url(_redis_url)
            logger.info("Using Redis-backed rate limiter")
        except Exception as e:
            logger.warning("Redis client init failed for rate limiter: %s", e)
    rate_guard = RateLimitGuard(rate_limiter, redis_client=redis_client)
    budget_manager = SessionBudgetManager(BudgetConfig(max_tokens=100_000))
    slot_tracker = create_builtin_tracker()

    pipeline = MiddlewarePipeline()
    pipeline.add(RateLimitMiddleware(rate_guard))
    pipeline.add(BudgetMiddleware(budget_manager))
    pipeline.add(SlotTrackingMiddleware(slot_tracker))
    orchestrator.set_middleware_pipeline(pipeline)

    # Wire response cache (Redis-backed when available, in-memory fallback)
    response_cache = ResponseCache(redis_client=redis_client)
    orchestrator.set_response_cache(response_cache)

    return orchestrator


def _check_auth_config() -> None:
    """Refuse to start in production without authentication.

    When DEV_MODE is not set and neither JWT_SECRET_KEY nor API_KEY is
    configured, the server will exit with an error message explaining how
    to fix it.
    """
    dev_mode = os.environ.get("DEV_MODE", "").lower() in ("1", "true", "yes")
    jwt_secret = os.environ.get("JWT_SECRET_KEY", "")
    api_key = os.environ.get("API_KEY", "")

    if dev_mode:
        logger.warning(
            "DEV_MODE is enabled — authentication checks are skipped. "
            "Never use this in production."
        )
        return

    if not jwt_secret and not api_key:
        logger.error(
            "FATAL: No authentication configured. Set one of:\n"
            "  JWT_SECRET_KEY=<random-secret>   (recommended)\n"
            "  API_KEY=<your-key>               (simple auth)\n"
            "Or set DEV_MODE=true for local development."
        )
        raise SystemExit(1)


def create_main_app():
    """Build the app with orchestrator wired in and static files mounted."""
    from contextlib import asynccontextmanager
    import time

    _check_auth_config()

    orchestrator = build_orchestrator()

    @asynccontextmanager
    async def lifespan(app):
        app.state.start_time = time.monotonic()
        app.state.orchestrator = orchestrator
        logger.info("OpenChatShop starting up")
        yield
        logger.info("OpenChatShop shutting down — draining active sessions")
        # Notify all connected WebSocket clients about shutdown
        import asyncio
        _agent_sockets = getattr(app.state, 'agent_sockets', {})
        _customer_sockets = getattr(app.state, 'customer_sockets', {})
        shutdown_msg = json.dumps({"type": "server_shutdown", "data": {"message": "服务器正在维护，请稍后重连"}}, ensure_ascii=False)
        for ws in list(_customer_sockets.values()):
            try:
                await ws.send_text(shutdown_msg)
            except Exception:
                pass
        for ws in list(_agent_sockets.values()):
            try:
                await ws.send_text(shutdown_msg)
            except Exception:
                pass
        # Allow brief time for messages to be sent
        await asyncio.sleep(1)
        if hasattr(app.state, 'redis_client') and app.state.redis_client:
            await app.state.redis_client.aclose()
        if hasattr(app.state, 'db_engine') and app.state.db_engine:
            app.state.db_engine.dispose()
        logger.info("OpenChatShop shutdown complete")

    app = create_app(orchestrator, lifespan=lifespan, agent_token=os.environ.get("AGENT_TOKEN"))

    # Serve React frontend (built) if available, fall back to static/
    frontend_dist = Path(__file__).parent / "frontend" / "dist"
    static_dir = Path(__file__).parent / "static"
    serve_dir = frontend_dist if frontend_dist.is_dir() else static_dir
    if serve_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(serve_dir), html=True), name="static")

    return app


app = create_main_app()

if __name__ == "__main__":
    host = os.environ.get("APP_HOST", "0.0.0.0")
    port = int(os.environ.get("APP_PORT", "8000"))
    uvicorn.run(app, host=host, port=port, timeout_graceful_shutdown=10)
