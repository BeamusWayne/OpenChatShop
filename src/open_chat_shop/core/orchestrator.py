"""Dialogue Orchestrator — coordinates all modules."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from open_chat_shop.core.types import (
    UserMessage,
    AgentMessage,
    SessionContext,
    Action,
)
from open_chat_shop.core.exceptions import (
    SecurityError,
    ContextError,
    ToolError,
    OpenChatShopError,
)

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
        self._session_locks: dict[str, asyncio.Lock] = {}

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

        # 3. Intent recognition
        intent = await self._intent_engine.classify(message, context)

        # 4. Dynamic tool injection
        tools = await self._tool_injector.inject(intent, context)

        # 5. Strategy decision
        action = await self._strategy.decide(intent, context, tools)

        # 6. Execute action
        response = await self._execute_action(action, context, tools)

        # 7. Update context
        await self._context_manager.save(context, response)

        return response

    async def _execute_action(
        self,
        action: Action,
        context: SessionContext,
        tools: list[Any],
    ) -> AgentMessage:
        """Dispatch action by type."""
        match action.type:
            case "reply":
                return AgentMessage(
                    message_type=action.payload.get("message_type", "text"),
                    payload=action.payload,
                    text_fallback=action.payload.get("content", ""),
                )

            case "tool_call":
                return await self._execute_tool(action, context, tools)

            case "confirm":
                return AgentMessage(
                    message_type="confirm",
                    payload=action.payload,
                    text_fallback=action.payload.get("description", ""),
                    requires_confirmation=True,
                )

            case "clarify":
                return AgentMessage(
                    message_type="text",
                    payload=action.payload,
                    text_fallback=action.payload.get("question", ""),
                )

            case "transfer":
                return AgentMessage(
                    message_type="transfer",
                    payload=action.payload,
                    text_fallback="正在为您转接人工客服...",
                )

            case "end":
                return AgentMessage(
                    message_type="text",
                    payload={"content": action.payload.get("summary", "")},
                    text_fallback=action.payload.get("summary", ""),
                )

            case "switch_scenario":
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
            text = tool.format_result(result)
            return AgentMessage(
                message_type="text",
                payload={"content": text, "tool_result": result.data},
                text_fallback=text,
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
