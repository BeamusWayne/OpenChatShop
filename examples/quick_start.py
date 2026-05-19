"""Quick Start Demo - OpenChatShop in 30 seconds.

Usage:
    python examples/quick_start.py
"""
import asyncio
from open_chat_shop.core.types import UserMessage
from open_chat_shop.core.provider import MockProvider
from open_chat_shop.core.context import InMemoryContextManager
from open_chat_shop.core.intent import CascadeIntentEngine, RuleBasedMatcher
from open_chat_shop.core.security import SecurityGuard
from open_chat_shop.core.tool import ToolInjector
from open_chat_shop.core.strategy import RuleBasedStrategy
from open_chat_shop.core.orchestrator import DialogueOrchestrator


async def main():
    # Setup mock components
    security = SecurityGuard({"rbac": {"roles": [{"name": "customer", "tools": ["*"]}]}})
    context_mgr = InMemoryContextManager()
    matcher = RuleBasedMatcher()
    matcher.add_rule("query_order", r"订单|order")
    matcher.add_rule("search_product", r"搜索|找|商品|search")
    matcher.add_rule("handoff_to_human", r"人工|客服")
    intent_engine = CascadeIntentEngine(matcher)
    tool_injector = ToolInjector({}, [])
    strategy = RuleBasedStrategy()

    orchestrator = DialogueOrchestrator(
        security, context_mgr, intent_engine, tool_injector, strategy,
    )

    # Chat!
    messages = [
        "你好！",
        "我想查一下订单状态",
        "帮我找一下蓝牙耳机",
        "我要转人工客服",
    ]

    for text in messages:
        msg = UserMessage(session_id="demo-1", content=text, channel="web")
        response = await orchestrator.handle_message(msg)
        print(f"用户: {text}")
        print(f"Agent: {response.text_fallback}")
        print()


if __name__ == "__main__":
    asyncio.run(main())
