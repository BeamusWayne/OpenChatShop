"""Middleware pipeline for the Dialogue Orchestrator.

Provides pre/post hooks around message processing so that cross-cutting
concerns (rate limiting, budget enforcement, slot tracking) are composed
declaratively instead of scattered through the orchestrator core.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from open_chat_shop.core.cost_governance import SessionBudgetManager
from open_chat_shop.core.rate_limiter import RateLimitGuard, RateLimitResult
from open_chat_shop.core.slot_tracker import SlotTracker
from open_chat_shop.core.types import AgentMessage, SessionContext, UserMessage

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


class Middleware(ABC):
    """Base class for orchestrator middleware.

    Subclasses implement ``pre_process`` (run *before* the orchestrator
    handles the message) and ``post_process`` (run *after* the response
    is produced).

    ``pre_process`` may return ``None`` to signal that the request should
    be short-circuited (blocked).  The pipeline will immediately return a
    blocked response without invoking the orchestrator or downstream
    middlewares' pre hooks.
    """

    @abstractmethod
    async def pre_process(
        self,
        message: UserMessage,
        context: SessionContext,
    ) -> UserMessage | None:
        """Inspect / modify *message* before orchestrator processing.

        Return the (possibly modified) message to continue the pipeline,
        or ``None`` to block the request.
        """

    @abstractmethod
    async def post_process(
        self,
        message: UserMessage,
        response: AgentMessage,
        context: SessionContext,
    ) -> AgentMessage:
        """Inspect / modify *response* after orchestrator processing."""


# ---------------------------------------------------------------------------
# Concrete middlewares
# ---------------------------------------------------------------------------


class RateLimitMiddleware(Middleware):
    """Block requests that exceed the configured rate limit.

    Uses :class:`RateLimitGuard` to enforce per-user message limits.
    When the limit is exceeded, ``pre_process`` returns ``None`` and
    stores a :class:`AgentMessage` on the instance so the pipeline can
    retrieve the blocked response.
    """

    def __init__(
        self,
        guard: RateLimitGuard,
        blocked_response: AgentMessage | None = None,
    ) -> None:
        self._guard = guard
        self._blocked_response = blocked_response or AgentMessage(
            message_type="text",
            payload={"content": "请求过于频繁，请稍后再试。"},
            text_fallback="请求过于频繁，请稍后再试。",
        )
        self.last_result: RateLimitResult | None = None

    async def pre_process(
        self,
        message: UserMessage,
        context: SessionContext,
    ) -> UserMessage | None:
        user_id = message.user_id or message.session_id
        result = self._guard.check_user(user_id)
        self.last_result = result
        if not result.allowed:
            logger.info(
                "Rate limit blocked user=%s remaining=%d",
                user_id,
                result.remaining,
            )
            return None
        return message

    async def post_process(
        self,
        message: UserMessage,
        response: AgentMessage,
        context: SessionContext,
    ) -> AgentMessage:
        return response


class BudgetMiddleware(Middleware):
    """Enforce per-session token budgets.

    Checks budget availability before processing; records token cost
    after processing using the ``token_usage`` metadata that downstream
    components may attach to the response.
    """

    def __init__(
        self,
        budget_manager: SessionBudgetManager,
        blocked_response: AgentMessage | None = None,
        default_cost: int = 100,
    ) -> None:
        self._budget = budget_manager
        self._blocked_response = blocked_response or AgentMessage(
            message_type="text",
            payload={"content": "当前会话预算已用尽，请稍后重试或开启新会话。"},
            text_fallback="当前会话预算已用尽，请稍后重试或开启新会话。",
        )
        self._default_cost = default_cost

    async def pre_process(
        self,
        message: UserMessage,
        context: SessionContext,
    ) -> UserMessage | None:
        if not self._budget.can_proceed(message.session_id):
            logger.info("Budget exhausted session=%s", message.session_id)
            return None
        return message

    async def post_process(
        self,
        message: UserMessage,
        response: AgentMessage,
        context: SessionContext,
    ) -> AgentMessage:
        cost = response.meta.get("token_usage", self._default_cost)
        if isinstance(cost, int):
            self._budget.consume(message.session_id, cost)
        return response


class SlotTrackingMiddleware(Middleware):
    """Extract and merge entities into the session slot tracker.

    Reads entities from ``message.metadata["entities"]`` (populated by
    upstream components such as the intent engine) and merges them into
    the session context slots via :class:`SlotTracker`.
    """

    def __init__(self, tracker: SlotTracker) -> None:
        self._tracker = tracker

    async def pre_process(
        self,
        message: UserMessage,
        context: SessionContext,
    ) -> UserMessage | None:
        entities: dict[str, Any] = message.metadata.get("entities", {})
        if entities and context.current_scenario:
            merged = self._tracker.merge_slots(context.slots, entities)
            # Update context immutably by replacing the slots dict
            context.slots = merged
        return message

    async def post_process(
        self,
        message: UserMessage,
        response: AgentMessage,
        context: SessionContext,
    ) -> AgentMessage:
        return response


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


class MiddlewarePipeline:
    """Ordered list of :class:`Middleware` instances.

    Usage::

        pipeline = MiddlewarePipeline([rl_mw, budget_mw, slot_mw])
        response = await pipeline.handle(message, context, orchestrator)

    *Pre hooks* run in list order; the first ``pre_process`` that returns
    ``None`` short-circuits the pipeline and returns a blocked response
    produced by ``_blocked_response(middleware, message)``.

    *Post hooks* run in reverse order so that the outermost middleware
    wraps the response last.
    """

    def __init__(self, middlewares: list[Middleware] | None = None) -> None:
        self._middlewares: list[Middleware] = list(middlewares or [])

    @property
    def middlewares(self) -> list[Middleware]:
        return list(self._middlewares)

    def add(self, middleware: Middleware) -> None:
        self._middlewares.append(middleware)

    async def handle(
        self,
        message: UserMessage,
        context: SessionContext,
        handler: Any,
    ) -> AgentMessage:
        """Run pre hooks, call *handler*, then run post hooks.

        *handler* must be an async callable that accepts a
        :class:`UserMessage` and returns an :class:`AgentMessage`.
        """
        # --- Pre hooks (forward order) ---
        current_msg: UserMessage | None = message
        for mw in self._middlewares:
            current_msg = await mw.pre_process(current_msg, context)
            if current_msg is None:
                return self._blocked_response(mw, message)
            message = current_msg

        # --- Core handler ---
        response = await handler(message)

        # --- Post hooks (reverse order) ---
        for mw in reversed(self._middlewares):
            response = await mw.post_process(message, response, context)

        return response

    @staticmethod
    def _blocked_response(
        middleware: Middleware,
        original_message: UserMessage,
    ) -> AgentMessage:
        """Produce a blocked response from the middleware that returned None."""
        if isinstance(middleware, RateLimitMiddleware):
            return middleware._blocked_response
        if isinstance(middleware, BudgetMiddleware):
            return middleware._blocked_response
        return AgentMessage(
            message_type="text",
            payload={"content": "请求被拦截"},
            text_fallback="请求被拦截",
        )
