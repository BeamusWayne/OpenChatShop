"""Dialogue Orchestrator — coordinates all modules."""
from __future__ import annotations

import asyncio
import logging
import re as _re
import time
from contextlib import AbstractContextManager
from contextlib import nullcontext as _nullcontext
from dataclasses import replace
from typing import Any, cast

from open_chat_shop.core.exceptions import (
    ContextError,
    SecurityError,
    ToolError,
)
from open_chat_shop.core.intent import _extract_entities
from open_chat_shop.core.tool_response_mapper import ToolResponseMapper
from open_chat_shop.core.types import (
    Action,
    AgentMessage,
    Intent,
    Message,
    SessionContext,
    SessionMode,
    UserMessage,
)

# Tracing — safe no-op if opentelemetry is not installed
try:
    from open_chat_shop.observability.tracing import (
        trace_context_load,
        trace_intent_classify,
        trace_orchestrator_handle,
        trace_security_check,
        trace_tool_execute,
        trace_tool_inject,
    )
    _TRACING_AVAILABLE = True
except ImportError:
    _TRACING_AVAILABLE = False

# Metrics — safe no-op if prometheus_client is not installed
try:
    from open_chat_shop.observability.metrics import (
        ACTIVE_SESSIONS,
        observe_chat_duration,
        record_cache_hit,
        record_chat_request,
        record_llm_call,
        record_tool_call,
    )
    _METRICS_AVAILABLE = True
except ImportError:
    _METRICS_AVAILABLE = False

logger = logging.getLogger(__name__)


class DialogueOrchestrator:
    """Coordinates security, context, intent, tools, and strategy."""

    def __init__(
        self,
        security_guard: Any,
        context_manager: Any,
        intent_engine: Any,
        tool_injector: Any,
        strategy: Any,
    ) -> None:
        self._security = security_guard
        self._context_manager = context_manager
        self._intent_engine = intent_engine
        self._tool_injector = tool_injector
        self._strategy = strategy
        self._provider: Any = None
        self._audit_logger: Any = None
        self._cost_tracker: Any = None
        self._session_locks: dict[str, asyncio.Lock] = {}
        self._SESSION_LOCKS_CAP = 10000
        self._tool_response_mapper: ToolResponseMapper | None = None
        self._scenarios: dict[str, Any] = {}
        self._handoff_queue: Any = None
        self._middleware_pipeline: Any = None
        self._response_cache: Any = None

    def set_provider(self, provider: Any) -> None:
        """Inject an LLM provider for natural language response generation.

        When set, the provider is used to enhance responses instead of
        returning hard-coded template text.  Pass None to revert to
        template-based replies.
        """
        self._provider = provider

    def set_audit_logger(self, audit_logger: Any) -> None:
        """Inject an audit logger for recording tool executions."""
        self._audit_logger = audit_logger

    def set_cost_tracker(self, cost_tracker: Any) -> None:
        """Inject a cost tracker for recording LLM token usage."""
        self._cost_tracker = cost_tracker

    def set_tool_response_mapper(self, mapper: ToolResponseMapper | None) -> None:
        """Inject a ToolResponseMapper for rich tool-result messages.

        When set, tool results are mapped to the correct AgentMessage type
        (order_card, logistics_timeline, etc.) instead of plain text.
        """
        self._tool_response_mapper = mapper

    def set_scenarios(self, scenarios: dict[str, Any]) -> None:
        """Register scenario FSMs keyed by scenario name."""
        self._scenarios = scenarios

    def set_handoff_queue(self, queue: Any) -> None:
        """Inject a HandoffQueue for human-agent transfer tracking."""
        self._handoff_queue = queue

    def set_middleware_pipeline(self, pipeline: Any) -> None:
        """Inject a MiddlewarePipeline for rate limiting, budget, and slot tracking.

        When set, the pipeline wraps core message processing so that
        pre/post hooks run before and after intent classification + tool
        execution.  Pass None to disable middleware.
        """
        self._middleware_pipeline = pipeline

    def set_response_cache(self, cache: Any) -> None:
        """Inject a ResponseCache for caching read-only query responses.

        When set, the cache is checked before intent classification for
        supported intents and populated after successful execution.
        """
        self._response_cache = cache

    def _trace_extras(self, session_id: str = "") -> dict[str, str]:
        """Build structured log extras with trace_id / span_id when available."""
        extras: dict[str, str] = {}
        if session_id:
            extras["session_id"] = session_id
        if _TRACING_AVAILABLE:
            try:
                from opentelemetry import trace

                span = trace.get_current_span()
                ctx = span.get_span_context()
                if ctx.is_valid:
                    extras["trace_id"] = format(ctx.trace_id, "032x")
                    extras["span_id"] = format(ctx.span_id, "016x")
            except Exception:
                pass
        return extras

    async def handle_message(self, message: UserMessage) -> AgentMessage:
        """Process user message, return agent reply.
        Same session_id processed serially via async lock.
        """
        # Evict oldest IDLE locks when cap exceeded. A lock that is currently
        # held belongs to an in-flight request for that session; evicting it
        # would let a concurrent message for the SAME session setdefault a
        # brand-new lock and enter _handle_internal in parallel, breaking the
        # per-session serial guarantee (audit MEDIUM). Skip held locks; only
        # remove ones with no waiter so the invariant holds under load.
        if len(self._session_locks) > self._SESSION_LOCKS_CAP:
            removed = 0
            for key in list(self._session_locks.keys()):
                if removed >= 5000:
                    break
                if not self._session_locks[key].locked():
                    del self._session_locks[key]
                    removed += 1
        lock = self._session_locks.setdefault(message.session_id, asyncio.Lock())
        async with lock:
            if _METRICS_AVAILABLE:
                ACTIVE_SESSIONS.set(len(self._session_locks))
            start = time.monotonic()
            response: AgentMessage | None = None
            try:
                response = await self._handle_internal(message)
                return response
            finally:
                if _METRICS_AVAILABLE:
                    label = (
                        str(response.meta.get("intent") or "unknown")
                        if response is not None else "unknown"
                    )
                    status = (
                        "success"
                        if response is not None and response.message_type != "error"
                        else "error"
                    )
                    record_chat_request(label, status)
                    observe_chat_duration(label, time.monotonic() - start)

    async def _handle_internal(self, message: UserMessage) -> AgentMessage:
        outer_span: AbstractContextManager[Any] = _nullcontext()
        if _TRACING_AVAILABLE:
            outer_span = trace_orchestrator_handle(message.session_id)

        with outer_span:
            # 1. Security check
            sec_span: AbstractContextManager[Any] = _nullcontext()
            if _TRACING_AVAILABLE:
                sec_span = trace_security_check()
            with sec_span:
                try:
                    # check_input masks any PII and returns the sanitised
                    # message; reassign so masked content flows downstream
                    # (intent, LLM, history, tools) instead of raw PII.
                    message = self._security.check_input(message)
                except SecurityError as e:
                    logger.warning(
                        "Security check blocked message",
                        extra={
                            **self._trace_extras(message.session_id),
                            "error": e.message,
                        },
                    )
                    return self._error_response("您的消息包含不当内容，请修改后重试。")

            # 2. Load context
            ctx_span: AbstractContextManager[Any] = _nullcontext()
            if _TRACING_AVAILABLE:
                ctx_span = trace_context_load(message.session_id)
            with ctx_span:
                try:
                    context = await self._context_manager.load(
                        message.session_id, channel=message.channel
                    )
                except ContextError:
                    return self._error_response("会话已过期，请重新开始。")

            # 2.05 Bind the verified caller identity onto the context BEFORE any
            # tool runs (audit CRITICAL-1). app.py already binds the JWT 'sub'
            # onto message.user_id; the order tools enforce ownership via
            # get_for_user(order_id, context.user_id), so the identity MUST
            # reach context.user_id or every order op runs with user_id=None
            # (ownership check skipped -> IDOR/BOLA). If the session was already
            # bound to a different non-None user, refuse rather than let a
            # second identity take over an in-flight session.
            if message.user_id is not None:
                if (
                    context.user_id is not None
                    and context.user_id != message.user_id
                ):
                    logger.warning(
                        "Session user_id mismatch; refusing identity takeover",
                        extra={
                            **self._trace_extras(message.session_id),
                            "bound_user": context.user_id,
                            "message_user": message.user_id,
                        },
                    )
                    return self._error_response("会话身份校验失败，请重新登录后再试。")
                context.user_id = message.user_id

            # 2.1 Session mode guard — bot must not respond in HUMAN mode
            if context.mode == SessionMode.HUMAN_MODE:
                return AgentMessage(
                    message_type="text",
                    payload={"content": "当前会话由人工客服为您服务，如需结束人工服务请告知客服。"},
                    text_fallback="当前会话由人工客服为您服务，如需结束人工服务请告知客服。",
                )
            if context.mode == SessionMode.TRANSFER_PENDING:
                return AgentMessage(
                    message_type="transfer",
                    payload={"status": "waiting"},
                    text_fallback="正在为您转接人工客服，请稍候...",
                )

            # If middleware pipeline is configured, wrap core processing with it.
            if self._middleware_pipeline is not None:
                async def core_handler(msg: UserMessage) -> AgentMessage:
                    return await self._core_handle(msg, context)
                return cast(
                    AgentMessage,
                    await self._middleware_pipeline.handle(
                        message, context, core_handler
                    ),
                )

            return await self._core_handle(message, context)

    async def _core_handle(
        self,
        message: UserMessage,
        context: SessionContext,
    ) -> AgentMessage:
        """Core processing: pending check, intent, tools, strategy, execution."""
        # 2.4 Check if user is answering a pending high-risk confirmation.
        # Runs before classification so an affirmative "确认" is not re-routed.
        pending_confirmation = context.slots.get("_pending_confirmation")
        if pending_confirmation is not None:
            confirm_response = await self._resolve_pending_confirmation(
                message, context, pending_confirmation,
            )
            if confirm_response is not None:
                self._record_turn(context, message, confirm_response)
                await self._context_manager.save(context, confirm_response)
                return confirm_response
            # Cleared (topic switch / ambiguous) — fall through to normal flow.

        # 2.5 Check if user is answering a previous clarification
        pending_action = context.slots.get("_pending_action")
        if pending_action is not None:
            # Detect topic switch: if user's input strongly matches a
            # different intent, clear pending and process the new request.
            quick_intent = self._intent_engine._rule_matcher.match(message.content)
            if (
                quick_intent is not None
                and quick_intent.confidence >= 0.8
                and quick_intent.name != pending_action.get("intent_name")
            ):
                context.slots.pop("_pending_action", None)
                logger.info(
                    "Topic switch detected, clearing pending action",
                    extra={
                        **self._trace_extras(),
                        "new_intent": quick_intent.name,
                        "old_pending": pending_action.get("intent_name"),
                    },
                )
            else:
                pending_response = await self._try_resolve_pending(
                    message, context, pending_action,
                )
                if pending_response is not None:
                    self._record_turn(context, message, pending_response)
                    await self._context_manager.save(context, pending_response)
                    return pending_response

        # 3. Intent recognition
        intent_span: AbstractContextManager[Any] = _nullcontext()
        if _TRACING_AVAILABLE:
            intent_span = trace_intent_classify(source="cascade")
        with intent_span:
            intent = await self._intent_engine.classify(message, context)

        # 3.5 Cache lookup for read-only intents. Scope by context.user_id so one
        # user's cached order data is never served to another (audit C4); the
        # cache folds user_id into its key.
        if self._response_cache is not None:
            params = dict(intent.entities) if intent.entities else {}
            params["content"] = message.content
            cached = self._response_cache.get(
                intent.name, params, user_id=context.user_id
            )
            if cached is not None:
                if _METRICS_AVAILABLE:
                    record_cache_hit(intent.name)
                self._record_turn(context, message, cached)
                await self._context_manager.save(context, cached)
                return cast(AgentMessage, cached)

        # 4. Dynamic tool injection
        inject_span: AbstractContextManager[Any] = _nullcontext()
        if _TRACING_AVAILABLE:
            inject_span = trace_tool_inject(intent.name)
        with inject_span:
            tools = await self._tool_injector.inject(intent, context)

        # 5. Strategy decision
        action = await self._strategy.decide(intent, context, tools)

        # 5.5 Persist multi-turn state: clarify slots, or a high-risk confirmation
        if action.type == "clarify" and "_pending_action" in action.payload:
            context.slots["_pending_action"] = action.payload["_pending_action"]
        elif action.type == "confirm" and "pending_action" in action.payload:
            context.slots["_pending_confirmation"] = action.payload["pending_action"]

        # 6. Execute action
        response = await self._execute_action(action, context, tools)

        # 6.1 Record structured routing facts on response.meta (audit CRITICAL-4).
        # The channel payload carries rich-message content, not the intent/tool
        # facts the regression harness and observability need — expose them here.
        executed_tool = (
            action.payload.get("tool_name", "")
            if action.type == "tool_call"
            else ""
        )
        response.meta = {
            **response.meta,  # preserve token_usage attached by the LLM layer
            "intent_name": intent.name,
            "intent_source": intent.source,
            "entities": dict(intent.entities),
            "tool_calls": [executed_tool] if executed_tool else [],
        }

        # 6.5 Cache successful responses for read-only intents, scoped to the
        # caller's user_id so cached order data stays per-user (audit C4).
        if self._response_cache is not None and response.message_type != "error":
            params = dict(intent.entities) if intent.entities else {}
            params["content"] = message.content
            self._response_cache.set(
                intent.name, params, response, user_id=context.user_id
            )

        # 7. Record this turn in history, then persist context (audit MEDIUM:
        # restores multi-turn memory for InMemory/Redis backends).
        self._record_turn(context, message, response)
        await self._context_manager.save(context, response)

        return response

    # ------------------------------------------------------------------
    # High-risk confirmation loop (audit HIGH-9)
    # ------------------------------------------------------------------

    # Rule-based affirmation detection. Negation is checked first so that
    # replies like "不确定"/"不可以" resolve to deny, never affirm (fail-safe).
    _DENY_RE = _re.compile(r"不|否|取消|算了|别|放弃|拒绝|cancel|\bno\b", _re.IGNORECASE)
    _AFFIRM_RE = _re.compile(
        r"^(好|好的|是|是的|对|对的|嗯+|可以|行)$"
        r"|确认|确定|同意|没错|执行|继续|\byes\b|\bok\b|\bsure\b",
        _re.IGNORECASE,
    )
    # Interrogative markers. A reply that asks a question ("确定吗？",
    # "确认一下是哪个订单") is NOT consent and must never trigger the
    # irreversible write, even though it contains an affirmation token as a
    # substring (audit HIGH). Question-form replies resolve to None so the
    # caller falls through to normal classification instead of executing.
    _QUESTION_RE = _re.compile(r"[?？]|吗|嘛|呢|哪|多少|几个|怎么|为什么|什么时候")

    @staticmethod
    def _detect_affirmation(text: str) -> str | None:
        """Classify a confirmation reply as 'affirm', 'deny', or None.

        Deterministic rule match (Rule 5: code answers what code can). A
        non-affirmative reply never triggers the irreversible write. Explicit
        negations and question-form replies are both treated as non-consent.
        """
        stripped = text.strip()
        if DialogueOrchestrator._DENY_RE.search(stripped):
            return "deny"
        # A clarifying/interrogative reply is not a "yes" — bail out before the
        # affirm match so "确定吗？" / "能确认下金额吗" do not execute the write.
        if DialogueOrchestrator._QUESTION_RE.search(stripped):
            return None
        if DialogueOrchestrator._AFFIRM_RE.search(stripped):
            return "affirm"
        return None

    async def _resolve_pending_confirmation(
        self,
        message: UserMessage,
        context: SessionContext,
        pending: dict[str, Any],
    ) -> AgentMessage | None:
        """Resolve a persisted high-risk confirmation from the user's reply.

        One-shot: the pending confirmation is always cleared. Returns the tool
        result on affirmation, a cancellation message on explicit decline, or
        None when the reply is unrelated (topic switch / ambiguous) so the
        caller proceeds with normal classification. Because any non-affirmative
        reply discards it, the confirmation is implicitly valid for a single
        turn — no explicit TTL is needed.
        """
        signal = self._detect_affirmation(message.content)
        context.slots.pop("_pending_confirmation", None)

        if signal == "affirm":
            tool_name = pending.get("tool_name", "")
            tool = (
                self._tool_injector.get_tool(tool_name)
                if hasattr(self._tool_injector, "get_tool")
                else None
            )
            if tool is None:
                return self._error_response("抱歉，该操作已失效，请重新发起。")
            logger.info(
                "Pending confirmation accepted",
                extra={
                    **self._trace_extras(context.session_id),
                    "tool_name": tool_name,
                },
            )
            action = Action(
                type="tool_call",
                payload={
                    "tool_name": tool_name,
                    "params": pending.get("params", {}),
                    "call_id": pending.get("call_id", f"call-{tool_name}"),
                },
            )
            return await self._execute_action(action, context, [tool])

        if signal == "deny":
            logger.info(
                "Pending confirmation declined",
                extra={
                    **self._trace_extras(context.session_id),
                    "tool_name": pending.get("tool_name"),
                },
            )
            return self._error_response("好的，已为您取消该操作。")

        # Unrelated / ambiguous — discard and let normal classification run.
        return None

    async def _try_resolve_pending(
        self,
        message: UserMessage,
        context: SessionContext,
        pending: dict[str, Any],
    ) -> AgentMessage | None:
        """Attempt to fill pending missing slots from the user's response.

        Returns a complete AgentMessage if all slots are now filled,
        or *None* if the user's input doesn't resolve the pending action
        and the normal intent-classification flow should proceed instead.
        """
        pending_intent_name: str = pending.get("intent_name", "")
        missing_slots: list[str] = pending.get("missing_slots", [])
        tool_name: str | None = pending.get("tool_name")
        existing_params: dict[str, Any] = dict(pending.get("params", {}))

        # Extract entities using the intent-aware extractor
        entities: dict[str, Any] = _extract_entities(
            message.content, pending_intent_name,
        )

        # Specific slot extraction (regex-based)
        for slot in missing_slots:
            if slot in entities:
                continue
            if slot == "order_id":
                m = _re.search(r"ORD-[\w]+", message.content, _re.IGNORECASE)
                if m:
                    entities["order_id"] = m.group(0)

        # Generic fallback: only if no specific slot was filled above
        specific_filled = any(s in entities for s in ("order_id", "keyword"))
        if not specific_filled:
            for slot in missing_slots:
                if slot in entities:
                    continue
                if slot == "keyword":
                    entities["keyword"] = message.content.strip()
                elif slot == "reason":
                    entities["reason"] = message.content.strip()
                elif slot == "new_address":
                    entities["new_address"] = message.content.strip()
                break  # One generic slot per message

        still_missing = [s for s in missing_slots if s not in entities]

        if still_missing:
            # Partial fill — keep pending and return a clarify message
            updated_params = {**existing_params, **entities}
            context.slots["_pending_action"] = {
                "intent_name": pending_intent_name,
                "missing_slots": still_missing,
                "tool_name": tool_name,
                "params": updated_params,
            }
            prompt = self._slot_prompt(still_missing)
            return AgentMessage(
                message_type="text",
                payload={"content": prompt, "question": prompt},
                text_fallback=prompt,
            )

        # All slots filled — build a synthetic intent and execute directly
        merged_params = {**existing_params, **entities}
        context.slots.pop("_pending_action", None)

        pending_intent = Intent(
            name=pending_intent_name,
            display_name=pending_intent_name,
            confidence=1.0,
            # Synthetic intent recovered from a persisted pending action; the
            # "context" source is a deliberate runtime marker that flows into
            # response meta (intent_source) and is outside the Intent.source
            # Literal owned by core/types.py.
            source="context",  # type: ignore[arg-type]
            entities=merged_params,
        )
        tools = await self._tool_injector.inject(pending_intent, context)

        # Build a tool_call action with the complete params
        if tool_name:
            action = Action(
                type="tool_call",
                payload={
                    "tool_name": tool_name,
                    "params": merged_params,
                    "call_id": f"call-{pending_intent_name}",
                },
            )
            return await self._execute_action(action, context, tools)

        # No tool — use strategy to decide
        action = await self._strategy.decide(pending_intent, context, tools)
        return await self._execute_action(action, context, tools)

    @staticmethod
    def _slot_prompt(missing_slots: list[str]) -> str:
        prompts = {
            "order_id": "请问您的订单号是多少？例如 ORD-001",
            "keyword": "请问您想搜索什么商品？",
            "reason": "请问退款原因是什么？",
            "new_address": "请问新的收货地址是什么？",
        }
        first = missing_slots[0]
        return prompts.get(first, f"请提供以下信息：{', '.join(missing_slots)}")

    async def _execute_action(
        self,
        action: Action,
        context: SessionContext,
        tools: list[Any],
    ) -> AgentMessage:
        """Dispatch action by type."""
        match action.type:
            case "reply":
                llm_msg = await self._llm_enhance(action, context)
                if llm_msg is not None:
                    return llm_msg
                return AgentMessage(
                    message_type=action.payload.get("message_type", "text"),
                    payload=action.payload,
                    text_fallback=action.payload.get("content", ""),
                )

            case "tool_call":
                return await self._execute_tool(action, context, tools)

            case "confirm":
                llm_msg = await self._llm_enhance(action, context)
                if llm_msg is not None:
                    return llm_msg
                return AgentMessage(
                    message_type="confirm",
                    payload=action.payload,
                    text_fallback=action.payload.get("description", ""),
                    requires_confirmation=True,
                )

            case "clarify":
                llm_msg = await self._llm_enhance(action, context)
                if llm_msg is not None:
                    return llm_msg
                return AgentMessage(
                    message_type="text",
                    payload=action.payload,
                    text_fallback=action.payload.get("question", ""),
                )

            case "transfer":
                if self._handoff_queue is not None:
                    try:
                        from open_chat_shop.core.handoff import TransferRequest
                        request = TransferRequest(
                            request_id=f"tr-{context.session_id}",
                            session_id=context.session_id,
                            user_id=context.user_id,
                            reason=action.payload.get("reason", "handoff"),
                            department=action.payload.get("department", "general"),
                        )
                        position = self._handoff_queue.enqueue(request)

                        # Try auto-assign to an available agent
                        assigned = self._handoff_queue.try_auto_assign()
                        if assigned is not None:
                            agent_id = assigned.assigned_agent_id
                            agent = self._handoff_queue._agents.get(agent_id or "")
                            agent_name = agent.name if agent else "客服"
                            msg = f"已为您接入人工客服 {agent_name}，请直接描述您的问题。"
                            action.payload["agent_name"] = agent_name
                            action.payload["status"] = "assigned"
                            # Set session to HUMAN_MODE — bot must stop responding
                            context.mode = SessionMode.HUMAN_MODE
                            context.human_agent_id = agent_id
                        else:
                            est_wait = self._handoff_queue.get_estimated_wait(context.session_id)
                            msg = (
                                f"正在为您转接人工客服，当前排队位置：第{position}位，"
                                f"预计等待约{est_wait // 60}分钟。"
                            )
                            action.payload["queue_position"] = position
                            action.payload["estimated_wait_seconds"] = est_wait
                            action.payload["status"] = "waiting"
                            # Set session to TRANSFER_PENDING — bot stays silent
                            context.mode = SessionMode.TRANSFER_PENDING
                    except Exception:
                        logger.warning("HandoffQueue enqueue failed, using fallback message")
                        msg = "正在为您转接人工客服..."
                        action.payload["status"] = "waiting"
                else:
                    msg = "正在为您转接人工客服..."
                    action.payload["status"] = "waiting"
                llm_msg = await self._llm_enhance(action, context)
                if llm_msg is not None:
                    return llm_msg
                return AgentMessage(
                    message_type="transfer",
                    payload=action.payload,
                    text_fallback=msg,
                )

            case "end":
                llm_msg = await self._llm_enhance(action, context)
                if llm_msg is not None:
                    return llm_msg
                return AgentMessage(
                    message_type="text",
                    payload={"content": action.payload.get("summary", "")},
                    text_fallback=action.payload.get("summary", ""),
                )

            case "switch_scenario":
                scenario_name = action.payload.get("scenario", "")
                scenario = self._scenarios.get(scenario_name)
                if scenario is not None:
                    initial_state = scenario.get_initial_state()
                    context.fsm_state = initial_state
                    context.current_scenario = scenario_name
                    # Try LLM enhancement for the scenario entry prompt
                    llm_msg = await self._llm_enhance(action, context)
                    fallback = f"已进入{scenario_name}流程，请按提示操作。"
                    if llm_msg is not None:
                        return AgentMessage(
                            message_type="text",
                            payload={"content": llm_msg.text_fallback},
                            text_fallback=llm_msg.text_fallback or fallback,
                        )
                    return AgentMessage(
                        message_type="text",
                        payload={"content": fallback},
                        text_fallback=fallback,
                    )
                # No scenario registered, fall back to LLM or plain text
                llm_msg = await self._llm_enhance(action, context)
                if llm_msg is not None:
                    return llm_msg
                return AgentMessage(
                    message_type="text",
                    payload={"content": f"切换到场景: {scenario_name}"},
                    text_fallback=f"切换到场景: {scenario_name}",
                )

            case _:
                return self._error_response("未知的操作类型")

    async def _execute_tool(
        self,
        action: Action,
        context: SessionContext,
        tools: list[Any],
    ) -> AgentMessage:
        """Execute a tool call with validation, pre-check, and compensation."""
        tool_name = action.payload.get("tool_name", "")
        params = action.payload.get("params", {})

        tool = next((t for t in tools if t.name == tool_name), None)
        if tool is None:
            return AgentMessage(
                message_type="text",
                payload={"content": f"工具 {tool_name} 不可用"},
                text_fallback=f"工具 {tool_name} 不可用",
            )

        # Security layer 3: RBAC gate — block execution if the session's role
        # is not permitted to use this tool. Runs before validation/execution.
        try:
            self._security.check_permission(context.user_role, tool_name)
        except SecurityError as e:
            logger.warning(
                "Tool execution blocked by RBAC",
                extra={
                    **self._trace_extras(context.session_id),
                    "role": context.user_role,
                    "tool_name": tool_name,
                    "error": e.message,
                },
            )
            if _METRICS_AVAILABLE:
                record_tool_call(tool_name, "blocked")
            return self._error_response("抱歉，您没有权限执行此操作。")

        # Parameter validation
        validation = tool.validate(params)
        if not validation.valid:
            return AgentMessage(
                message_type="text",
                payload={"content": "信息不完整，请提供所需信息后重试。"},
                text_fallback="信息不完整，请提供所需信息后重试。",
            )

        # Pre-check
        check = await tool.pre_check(params, context)
        if not check.passed:
            return AgentMessage(
                message_type="text",
                payload={"content": check.reason or "前置条件不满足"},
                text_fallback=check.reason or "前置条件不满足",
            )

        # Execute with compensation on failure
        exec_span: AbstractContextManager[Any] = _nullcontext()
        if _TRACING_AVAILABLE:
            exec_span = trace_tool_execute(tool_name)
        with exec_span:
            try:
                result = await tool.execute(params, context)
            except ToolError:
                await tool.compensate(params, context)
                if self._audit_logger is not None:
                    self._audit_logger.log_tool_execution(
                        tool_name=tool_name,
                        user_id=None,
                        session_id=context.session_id,
                        params=params,
                        result="failure",
                    )
                if _METRICS_AVAILABLE:
                    record_tool_call(tool_name, "error")
                return AgentMessage(
                    message_type="text",
                    payload={"content": "操作暂时无法完成，请稍后重试"},
                    text_fallback="操作暂时无法完成，请稍后重试",
                )

        # Audit log for tool execution result
        if self._audit_logger is not None:
            self._audit_logger.log_tool_execution(
                tool_name=tool_name,
                user_id=None,
                session_id=context.session_id,
                params=params,
                result="success" if result.success else "failure",
            )
        if _METRICS_AVAILABLE:
            record_tool_call(tool_name, "success" if result.success else "failure")

        # Build response from tool result
        if result.success:
            # Security layer 4: mask sensitive fields in the result before it
            # reaches format_result / rich payload / LLM enhancement / channel.
            if result.data is not None:
                result = replace(
                    result,
                    data=self._security.sanitize_output(
                        result.data, result.sensitive_fields or None
                    ),
                )
            formatted = tool.format_result(result)
            # Use mapper for rich message types when available
            if self._tool_response_mapper is not None:
                mapped = self._tool_response_mapper.map(tool.name, result, context)
                if mapped is not None:
                    # Optionally enhance text_fallback with LLM
                    enhanced, tokens = await self._llm_enhance_tool_result(
                        formatted, result.data, context,
                    )
                    if enhanced:
                        mapped = AgentMessage(
                            message_type=mapped.message_type,
                            payload=mapped.payload,
                            text_fallback=enhanced,
                            suggestions=mapped.suggestions,
                            requires_confirmation=mapped.requires_confirmation,
                            meta={"token_usage": tokens} if tokens else {},
                        )
                    return mapped
            # Fallback to original text behavior
            enhanced, tokens = await self._llm_enhance_tool_result(
                formatted, result.data, context,
            )
            return AgentMessage(
                message_type="text",
                payload={"content": enhanced or formatted},
                text_fallback=enhanced or formatted,
                meta={"token_usage": tokens} if tokens else {},
            )
        else:
            return AgentMessage(
                message_type="text",
                payload={"content": result.error or "操作失败"},
                text_fallback=result.error or "操作失败",
            )

    def _error_response(self, message: str) -> AgentMessage:
        return AgentMessage(
            message_type="text",
            payload={"content": message},
            text_fallback=message,
        )

    # ------------------------------------------------------------------
    # LLM enhancement helpers
    # ------------------------------------------------------------------

    def _provider_model_name(self) -> str:
        """Best-effort model identifier for cost attribution."""
        return (
            getattr(self._provider, "model", None)
            or getattr(self._provider, "name", None)
            or "unknown"
        )

    def _record_llm_cost(self, response: Any) -> int:
        """Record real token usage from an LLM response; return total tokens.

        Reads ``response.usage`` (set by the provider) and attributes the cost
        to the real model. Returns 0 when no usage data is present, so callers
        leave ``token_usage`` unset and the budget guard keeps its default.
        """
        usage = getattr(response, "usage", None)
        if usage is None:
            return 0
        if self._cost_tracker is not None:
            self._cost_tracker.record(
                model=self._provider_model_name(),
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
            )
        if _METRICS_AVAILABLE:
            record_llm_call(
                self._provider_model_name(),
                "success",
                usage.prompt_tokens,
                usage.completion_tokens,
            )
        return cast(int, usage.total_tokens)

    async def _llm_enhance(
        self,
        action: Action,
        context: SessionContext,
    ) -> AgentMessage | None:
        """Use LLM to generate natural reply based on action payload and history.

        Returns None when the provider is not available or the LLM call fails,
        so callers can fall back to template-based responses.
        """
        if self._provider is None:
            return None

        history_text = self._build_history_text(context)

        system_prompt = (
            "你是 OpenChatShop 电商智能客服。根据对话上下文和系统提供的信息，"
            "用自然、友好的语言回复用户。要求：\n"
            "1. 回复简洁，通常1-3句话\n"
            "2. 直接回答用户问题，不要重复已知信息\n"
            "3. 如果有具体数据（订单号、金额等），包含在回复中\n"
            "4. 用中文回复"
        )

        # Filter internal control fields from the payload before sending to the
        # LLM. The clarify path stores its routing dict under "_pending_action"
        # (caught by the underscore filter), but the confirm path stores it
        # under the NON-prefixed "pending_action" (strategy.py), which would
        # otherwise leak tool_name/params/call_id into the model prompt
        # (audit LOW). Drop the known internal keys explicitly too.
        _internal_keys = {"pending_action", "_pending_action", "missing_slots"}
        clean_payload = {
            k: v for k, v in action.payload.items()
            if not k.startswith("_") and k not in _internal_keys
        }

        user_prompt = (
            f"对话历史：\n{history_text}\n"
            f"系统信息：{clean_payload}\n请回复用户："
        )

        messages = [
            Message(role="system", content=system_prompt),
            Message(role="user", content=user_prompt),
        ]

        try:
            response = await self._provider.chat(messages)
        except Exception:
            logger.warning("LLM enhancement failed, falling back to template")
            return None

        tokens = self._record_llm_cost(response)

        return AgentMessage(
            message_type=action.payload.get("message_type", "text"),
            payload=action.payload,
            text_fallback=response.content,
            meta={"token_usage": tokens} if tokens else {},
        )

    async def _llm_enhance_tool_result(
        self,
        formatted: str,
        data: dict[str, Any] | None,
        context: SessionContext,
    ) -> tuple[str | None, int]:
        """Use LLM to rewrite a formatted tool result in natural language.

        Returns ``(text, token_usage)``. ``text`` is None when the provider is
        unavailable or the call fails; ``token_usage`` is the real token count
        recorded against the cost tracker (0 when no LLM call was made).
        """
        if self._provider is None:
            return None, 0

        history_text = self._build_history_text(context)

        system_prompt = (
            "你是 OpenChatShop 电商智能客服。根据对话上下文和工具返回的数据，"
            "用自然、友好的语言回复用户。要求：\n"
            "1. 回复简洁，通常1-3句话\n"
            "2. 直接回答用户问题，不要重复已知信息\n"
            "3. 如果有具体数据（订单号、金额等），包含在回复中\n"
            "4. 用中文回复"
        )

        data_section = (
            f"格式化结果：{formatted}\n原始数据：{data}"
            if data
            else f"格式化结果：{formatted}"
        )
        user_prompt = (
            f"对话历史：\n{history_text}\n"
            f"{data_section}\n请回复用户："
        )

        messages = [
            Message(role="system", content=system_prompt),
            Message(role="user", content=user_prompt),
        ]

        try:
            response = await self._provider.chat(messages)
        except Exception:
            logger.warning("LLM tool-result enhancement failed, using formatted text")
            return None, 0

        tokens = self._record_llm_cost(response)
        return response.content, tokens

    @staticmethod
    def _record_turn(
        context: SessionContext,
        message: UserMessage,
        response: AgentMessage,
    ) -> None:
        """Append the inbound user turn and the produced assistant turn to history.

        Nothing else in the source appends to ``context.history`` (audit
        MEDIUM), so for the InMemory/Redis backends the history window stays
        permanently empty and the intent engine (history[-3:]) and LLM prompt
        (history[-6:]) get no prior turns — the DB backend, which rebuilds
        history from ConversationLog rows, behaved inconsistently. Recording
        both turns here restores multi-turn memory on every backend, matching
        the (role, content) shape the DB backend reconstructs.
        """
        context.history.append(Message(role="user", content=message.content))
        context.history.append(
            Message(role="assistant", content=response.text_fallback)
        )

    def _build_history_text(self, context: SessionContext) -> str:
        """Build a compact text representation of recent conversation history."""
        lines: list[str] = []
        for msg in context.history[-6:]:
            role_label = "用户" if msg.role == "user" else "客服"
            lines.append(f"{role_label}: {msg.content}")
        return "\n".join(lines)
