"""handoff_to_human tool -- transfer the conversation to a human agent."""

from __future__ import annotations

from typing import Any

from open_chat_shop.core.tool import BaseTool
from open_chat_shop.core.types import SessionContext, ToolPermission, ToolResult
from open_chat_shop.storage.repositories.abc import HandoffRepository
from open_chat_shop.storage.repositories.memory import InMemoryHandoffRepository


class HandoffToHumanTool(BaseTool):
    """Transfer the current conversation to a human support agent."""

    name: str = "handoff_to_human"
    description: str = "Transfer to a human agent. Returns estimated wait time."
    category: str = "support"
    params_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "reason": {"type": "string", "description": "Optional reason for handoff"},
        },
        "required": [],
        "additionalProperties": False,
    }
    permissions: ToolPermission = ToolPermission(
        required_roles=["customer"],
        idempotent=True,
    )

    def __init__(self, handoff_repo: HandoffRepository | None = None) -> None:
        self._handoff_repo = handoff_repo or InMemoryHandoffRepository()

    async def execute(self, params: dict, context: SessionContext) -> ToolResult:
        reason = params.get("reason", "Customer requested human agent")
        return ToolResult(
            success=True,
            data={
                **self._handoff_repo.get_response(),
                "reason": reason,
            },
        )

    def format_result(self, result: ToolResult) -> str:
        data = result.data
        if not data:
            return "正在为您转接人工客服，请稍候。"
        lines = [
            "正在为您转接人工客服，请稍候。",
            f"排队位置：第 {data.get('queue_position', '?')} 位",
            f"预计等待时间：约 {data.get('estimated_wait_seconds', 0) // 60} 分钟",
        ]
        return "\n".join(lines)
