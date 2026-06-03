"""Tests for the middleware pipeline (feat-033)."""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from open_chat_shop.core.cost_governance import BudgetConfig, SessionBudgetManager
from open_chat_shop.core.middleware import (
    BudgetMiddleware,
    Middleware,
    MiddlewarePipeline,
    RateLimitMiddleware,
    SlotTrackingMiddleware,
)
from open_chat_shop.core.rate_limiter import InMemoryRateLimiter, RateLimitGuard, RateLimitRule
from open_chat_shop.core.slot_tracker import SlotDefinition, SlotTracker
from open_chat_shop.core.types import AgentMessage, SessionContext, UserMessage

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_message(
    session_id: str = "sess-1",
    user_id: str | None = "user-1",
    content: str = "hello",
    metadata: dict[str, Any] | None = None,
) -> UserMessage:
    return UserMessage(
        session_id=session_id,
        content=content,
        channel="web",
        user_id=user_id,
        metadata=metadata or {},
    )


def _make_context(
    session_id: str = "sess-1",
    scenario: str | None = None,
    slots: dict[str, Any] | None = None,
) -> SessionContext:
    return SessionContext(
        session_id=session_id,
        user_id="user-1",
        channel="web",
        current_scenario=scenario,
        slots=slots or {},
    )


async def _noop_handler(message: UserMessage) -> AgentMessage:
    return AgentMessage(
        message_type="text",
        payload={"content": f"echo: {message.content}"},
        text_fallback=f"echo: {message.content}",
    )


# ---------------------------------------------------------------------------
# RateLimitMiddleware
# ---------------------------------------------------------------------------


class TestRateLimitMiddleware:
    """RateLimitMiddleware delegates to RateLimitGuard."""

    @pytest.mark.asyncio
    async def test_allows_when_under_limit(self) -> None:
        """First request under the limit should pass through."""
        limiter = InMemoryRateLimiter()
        rule = RateLimitRule(key="user:{user_id}:msg", window_seconds=60, max_requests=5)
        guard = RateLimitGuard(limiter, {"user_messages": rule})
        mw = RateLimitMiddleware(guard)

        msg = _make_message()
        ctx = _make_context()
        result = await mw.pre_process(msg, ctx)

        assert result is not None
        assert result.content == "hello"

    @pytest.mark.asyncio
    async def test_blocks_when_over_limit(self) -> None:
        """Requests exceeding the limit should be blocked (return None)."""
        limiter = InMemoryRateLimiter()
        rule = RateLimitRule(key="user:{user_id}:msg", window_seconds=60, max_requests=2)
        guard = RateLimitGuard(limiter, {"user_messages": rule})
        mw = RateLimitMiddleware(guard)

        msg = _make_message()
        ctx = _make_context()

        # Consume the first two allowed requests
        assert await mw.pre_process(msg, ctx) is not None
        assert await mw.pre_process(msg, ctx) is not None

        # Third request should be blocked
        result = await mw.pre_process(msg, ctx)
        assert result is None

    @pytest.mark.asyncio
    async def test_falls_back_to_session_id_when_no_user_id(self) -> None:
        """When user_id is None, uses session_id for rate limiting."""
        limiter = InMemoryRateLimiter()
        rule = RateLimitRule(key="user:{user_id}:msg", window_seconds=60, max_requests=1)
        guard = RateLimitGuard(limiter, {"user_messages": rule})
        mw = RateLimitMiddleware(guard)

        msg = _make_message(user_id=None)
        ctx = _make_context()

        # First request passes
        assert await mw.pre_process(msg, ctx) is not None
        # Second blocked
        assert await mw.pre_process(msg, ctx) is None


# ---------------------------------------------------------------------------
# BudgetMiddleware
# ---------------------------------------------------------------------------


class TestBudgetMiddleware:
    """BudgetMiddleware checks and records session token budgets."""

    @pytest.mark.asyncio
    async def test_allows_when_budget_available(self) -> None:
        """Request passes when session has remaining budget."""
        budget = SessionBudgetManager(BudgetConfig(max_tokens=1000))
        mw = BudgetMiddleware(budget, default_cost=50)

        msg = _make_message()
        ctx = _make_context()
        result = await mw.pre_process(msg, ctx)

        assert result is not None

    @pytest.mark.asyncio
    async def test_blocks_when_budget_exhausted(self) -> None:
        """Request is blocked when session budget is fully consumed."""
        budget = SessionBudgetManager(BudgetConfig(max_tokens=100))
        mw = BudgetMiddleware(budget, default_cost=50)

        msg = _make_message()
        ctx = _make_context()

        # Drain the budget via post_process
        response = AgentMessage(
            message_type="text",
            payload={},
            text_fallback="ok",
            meta={"token_usage": 100},
        )
        await mw.post_process(msg, response, ctx)

        # Now pre_process should block
        result = await mw.pre_process(msg, ctx)
        assert result is None

    @pytest.mark.asyncio
    async def test_records_cost_on_post_process(self) -> None:
        """post_process records the real token cost from response.meta."""
        budget = SessionBudgetManager(BudgetConfig(max_tokens=1000))
        mw = BudgetMiddleware(budget, default_cost=50)

        msg = _make_message()
        ctx = _make_context()
        response = AgentMessage(
            message_type="text",
            payload={},
            text_fallback="ok",
            meta={"token_usage": 200},
        )

        await mw.post_process(msg, response, ctx)
        status = budget.get_status(msg.session_id)

        assert status.used_tokens == 200

    @pytest.mark.asyncio
    async def test_uses_default_cost_when_meta_has_no_usage(self) -> None:
        """post_process falls back to default_cost if meta lacks token_usage."""
        budget = SessionBudgetManager(BudgetConfig(max_tokens=1000))
        mw = BudgetMiddleware(budget, default_cost=75)

        msg = _make_message()
        ctx = _make_context()
        response = AgentMessage(
            message_type="text",
            payload={},
            text_fallback="ok",
        )

        await mw.post_process(msg, response, ctx)
        status = budget.get_status(msg.session_id)

        assert status.used_tokens == 75


# ---------------------------------------------------------------------------
# SlotTrackingMiddleware
# ---------------------------------------------------------------------------


class TestSlotTrackingMiddleware:
    """SlotTrackingMiddleware extracts entities and merges into context."""

    @pytest.mark.asyncio
    async def test_extracts_entities_from_metadata(self) -> None:
        """Entities in message metadata are merged into context slots."""
        tracker = SlotTracker()
        tracker.register_scenario("request_refund", [
            SlotDefinition(name="order_id", type="string", required=True),
            SlotDefinition(name="reason", type="string", required=False),
        ])
        mw = SlotTrackingMiddleware(tracker)

        msg = _make_message(metadata={"entities": {"order_id": "ORD-123"}})
        ctx = _make_context(scenario="request_refund", slots={})

        result = await mw.pre_process(msg, ctx)
        assert result is not None
        assert ctx.slots == {"order_id": "ORD-123"}

    @pytest.mark.asyncio
    async def test_no_merge_without_scenario(self) -> None:
        """Entities are not merged when no scenario is active."""
        tracker = SlotTracker()
        mw = SlotTrackingMiddleware(tracker)

        msg = _make_message(metadata={"entities": {"order_id": "ORD-123"}})
        ctx = _make_context(scenario=None, slots={})

        await mw.pre_process(msg, ctx)
        assert ctx.slots == {}

    @pytest.mark.asyncio
    async def test_no_merge_without_entities(self) -> None:
        """No merge happens when message has no entities."""
        tracker = SlotTracker()
        mw = SlotTrackingMiddleware(tracker)

        msg = _make_message(metadata={})
        ctx = _make_context(scenario="query_order", slots={"existing": "val"})

        await mw.pre_process(msg, ctx)
        assert ctx.slots == {"existing": "val"}

    @pytest.mark.asyncio
    async def test_merges_into_existing_slots(self) -> None:
        """New entities are merged on top of existing slot values."""
        tracker = SlotTracker()
        tracker.register_scenario("request_refund", [
            SlotDefinition(name="order_id", type="string", required=True),
        ])
        mw = SlotTrackingMiddleware(tracker)

        msg = _make_message(metadata={"entities": {"reason": "defective"}})
        ctx = _make_context(scenario="request_refund", slots={"order_id": "ORD-1"})

        await mw.pre_process(msg, ctx)
        assert ctx.slots == {"order_id": "ORD-1", "reason": "defective"}


# ---------------------------------------------------------------------------
# MiddlewarePipeline
# ---------------------------------------------------------------------------


class TestMiddlewarePipeline:
    """MiddlewarePipeline orchestrates ordered pre/post hooks."""

    @pytest.mark.asyncio
    async def test_runs_middlewares_in_order(self) -> None:
        """Middlewares run in the order they were added."""
        call_order: list[str] = []

        class OrderingMiddleware(Middleware):
            def __init__(self, name: str) -> None:
                self._name = name

            async def pre_process(
                self, message: UserMessage, context: SessionContext,
            ) -> UserMessage | None:
                call_order.append(f"pre_{self._name}")
                return message

            async def post_process(
                self, message: UserMessage, response: AgentMessage,
                context: SessionContext,
            ) -> AgentMessage:
                call_order.append(f"post_{self._name}")
                return response

        pipeline = MiddlewarePipeline([
            OrderingMiddleware("A"),
            OrderingMiddleware("B"),
        ])

        msg = _make_message()
        ctx = _make_context()
        result = await pipeline.handle(msg, ctx, _noop_handler)

        assert result.text_fallback == "echo: hello"
        assert call_order == ["pre_A", "pre_B", "post_B", "post_A"]

    @pytest.mark.asyncio
    async def test_pre_hook_can_block_request(self) -> None:
        """When a pre_hook returns None, the pipeline returns a blocked response."""
        limiter = InMemoryRateLimiter()
        rule = RateLimitRule(key="user:{user_id}:msg", window_seconds=60, max_requests=1)
        guard = RateLimitGuard(limiter, {"user_messages": rule})
        rl_mw = RateLimitMiddleware(guard)

        handler = AsyncMock(return_value=AgentMessage(
            message_type="text", payload={"content": "should not appear"},
            text_fallback="should not appear",
        ))

        pipeline = MiddlewarePipeline([rl_mw])
        msg = _make_message()
        ctx = _make_context()

        # First request passes
        r1 = await pipeline.handle(msg, ctx, handler)
        assert r1.text_fallback == "should not appear"

        # Second request blocked by rate limit
        r2 = await pipeline.handle(msg, ctx, handler)
        assert r2.text_fallback == "请求过于频繁，请稍后再试。"

    @pytest.mark.asyncio
    async def test_post_hook_can_modify_response(self) -> None:
        """Post hooks can modify the response before it is returned."""
        class EnrichMiddleware(Middleware):
            async def pre_process(
                self, message: UserMessage, context: SessionContext,
            ) -> UserMessage | None:
                return message

            async def post_process(
                self, message: UserMessage, response: AgentMessage,
                context: SessionContext,
            ) -> AgentMessage:
                return AgentMessage(
                    message_type=response.message_type,
                    payload={**response.payload, "enriched": True},
                    text_fallback=response.text_fallback,
                )

        pipeline = MiddlewarePipeline([EnrichMiddleware()])
        msg = _make_message()
        ctx = _make_context()
        result = await pipeline.handle(msg, ctx, _noop_handler)

        assert result.payload["enriched"] is True
        assert result.text_fallback == "echo: hello"

    @pytest.mark.asyncio
    async def test_empty_pipeline_passes_through(self) -> None:
        """An empty pipeline simply delegates to the handler."""
        pipeline = MiddlewarePipeline([])
        msg = _make_message()
        ctx = _make_context()
        result = await pipeline.handle(msg, ctx, _noop_handler)

        assert result.text_fallback == "echo: hello"

    @pytest.mark.asyncio
    async def test_add_middleware_appends(self) -> None:
        """Middleware added via add() runs after those in the constructor."""
        call_order: list[str] = []

        class StampMiddleware(Middleware):
            def __init__(self, stamp: str) -> None:
                self._stamp = stamp

            async def pre_process(
                self, message: UserMessage, context: SessionContext,
            ) -> UserMessage | None:
                call_order.append(self._stamp)
                return message

            async def post_process(
                self, message: UserMessage, response: AgentMessage,
                context: SessionContext,
            ) -> AgentMessage:
                return response

        pipeline = MiddlewarePipeline([StampMiddleware("first")])
        pipeline.add(StampMiddleware("second"))

        msg = _make_message()
        ctx = _make_context()
        await pipeline.handle(msg, ctx, _noop_handler)

        assert call_order == ["first", "second"]

    @pytest.mark.asyncio
    async def test_blocked_budget_returns_correct_response(self) -> None:
        """BudgetMiddleware blocked response is returned correctly via pipeline."""
        budget = SessionBudgetManager(BudgetConfig(max_tokens=10))
        mw = BudgetMiddleware(budget, default_cost=100)

        # Drain budget
        msg = _make_message()
        ctx = _make_context()
        await mw.post_process(msg, AgentMessage(
            message_type="text", payload={},
            text_fallback="ok", meta={"token_usage": 10},
        ), ctx)

        pipeline = MiddlewarePipeline([mw])
        result = await pipeline.handle(msg, ctx, _noop_handler)

        assert "预算已用尽" in result.text_fallback
