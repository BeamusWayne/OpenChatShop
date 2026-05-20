"""Dialogue Orchestrator — coordinates all modules."""
from __future__ import annotations

import asyncio
import logging
import re as _re
from typing import Any

from open_chat_shop.core.types import (
    Message,
    UserMessage,
    AgentMessage,
    SessionContext,
    Action,
    Intent,
)
from open_chat_shop.core.exceptions import (
    SecurityError,
    ContextError,
    ToolError,
    OpenChatShopError,
)
from open_chat_shop.core.intent import _extract_entities

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
        self._session_locks: dict[str, asyncio.Lock] = {}

    def set_provider(self, provider: Any) -> None:
        """Inject an LLM provider for natural language response generation.

        When set, the provider is used to enhance responses instead of
        returning hard-coded template text.  Pass None to revert to
        template-based replies.
        """
        self._provider = provider

    async def handle_message(self, message: UserMessage) -> AgentMessage:
        """Process user message, return agent reply.
        Same session_id processed serially via async lock.
        """
        lock = self._session_locks.setdefault(message.session_id, asyncio.Lock())
        async with lock:
            return await self._handle_internal(message)

    async def _handle_internal(self, message: UserMessage) -> AgentMessage:
        # 1. Security check
        try:
            self._security.check_input(message)
        except SecurityError as e:
            logger.warning("Security check blocked message", extra={
                "session_id": message.session_id, "error": e.message,
            })
            return self._error_response("您的消息包含不当内容，请修改后重试。")

        # 2. Load context
        try:
            context = await self._context_manager.load(message.session_id)
        except ContextError:
            return self._error_response("会话已过期，请重新开始。")

        # 2.5 Check if user is answering a previous clarification
        pending_action = context.slots.get("_pending_action")
        if pending_action is not None:
            pending_response = await self._try_resolve_pending(
                message, context, pending_action,
            )
            if pending_response is not None:
                await self._context_manager.save(context, pending_response)
                return pending_response
            # If resolution failed, fall through to normal flow

        # 3. Intent recognition
        intent = await self._intent_engine.classify(message, context)

        # 4. Dynamic tool injection
        tools = await self._tool_injector.inject(intent, context)

        # 5. Strategy decision
        action = await self._strategy.decide(intent, context, tools)

        # 5.5 Save pending action info to context when clarifying
        if action.type == "clarify" and "_pending_action" in action.payload:
            context.slots["_pending_action"] = action.payload["_pending_action"]

        # 6. Execute action
        response = await self._execute_action(action, context, tools)

        # 7. Update context
        await self._context_manager.save(context, response)

        return response

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
            source="context",
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
                llm_msg = await self._llm_enhance(action, context)
                if llm_msg is not None:
                    return llm_msg
                return AgentMessage(
                    message_type="transfer",
                    payload=action.payload,
                    text_fallback="正在为您转接人工客服...",
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
                llm_msg = await self._llm_enhance(action, context)
                if llm_msg is not None:
                    return llm_msg
                return AgentMessage(
                    message_type="text",
                    payload={"content": f"切换到场景: {action.payload.get('scenario', '')}"},
                    text_fallback=f"切换到场景: {action.payload.get('scenario', '')}",
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
        try:
            result = await tool.execute(params, context)
        except ToolError:
            await tool.compensate(params, context)
            return AgentMessage(
                message_type="text",
                payload={"content": "操作暂时无法完成，请稍后重试"},
                text_fallback="操作暂时无法完成，请稍后重试",
            )

        # Build response from tool result
        if result.success:
            formatted = tool.format_result(result)
            # Try to enhance tool result with LLM
            enhanced = await self._llm_enhance_tool_result(
                formatted, result.data, context,
            )
            return AgentMessage(
                message_type="text",
                payload={"content": enhanced or formatted},
                text_fallback=enhanced or formatted,
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

        # Filter internal fields from payload before sending to LLM
        clean_payload = {
            k: v for k, v in action.payload.items()
            if not k.startswith("_")
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

        return AgentMessage(
            message_type=action.payload.get("message_type", "text"),
            payload=action.payload,
            text_fallback=response.content,
        )

    async def _llm_enhance_tool_result(
        self,
        formatted: str,
        data: dict[str, Any] | None,
        context: SessionContext,
    ) -> str | None:
        """Use LLM to rewrite a formatted tool result in natural language.

        Returns None when the provider is not available or the LLM call fails.
        """
        if self._provider is None:
            return None

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
            return response.content
        except Exception:
            logger.warning("LLM tool-result enhancement failed, using formatted text")
            return None

    def _build_history_text(self, context: SessionContext) -> str:
        """Build a compact text representation of recent conversation history."""
        lines: list[str] = []
        for msg in context.history[-6:]:
            role_label = "用户" if msg.role == "user" else "客服"
            lines.append(f"{role_label}: {msg.content}")
        return "\n".join(lines)
