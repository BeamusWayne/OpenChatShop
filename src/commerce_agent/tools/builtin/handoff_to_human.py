"""handoff_to_human tool -- transfer the conversation to a human agent."""

from __future__ import annotations

from typing import Any

from commerce_agent.core.tool import BaseTool
from commerce_agent.core.types import SessionContext, ToolPermission, ToolResult

from commerce_agent.tools.builtin._mock_data import HANDOFF_RESPONSE


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

    async def execute(self, params: dict, context: SessionContext) -> ToolResult:
        reason = params.get("reason", "Customer requested human agent")
        return ToolResult(
            success=True,
            data={
                **HANDOFF_RESPONSE,
                "reason": reason,
            },
        )
