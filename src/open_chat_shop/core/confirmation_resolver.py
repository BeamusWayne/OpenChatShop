"""High-risk confirmation resolution (audit HIGH-9).

Extracted from :class:`DialogueOrchestrator` to keep the orchestrator focused
on coordination. This collaborator owns the rule-based affirmation detection
and the one-shot resolution of a persisted high-risk confirmation. It holds a
back-reference to the orchestrator (``host``) for the shared execution
primitives (``_execute_action``, ``_tool_injector``, ``_error_response``,
``_trace_extras``) — the resolution is inseparable from how the orchestrator
runs tools, so a narrow back-reference is the honest seam.
"""
from __future__ import annotations

import logging
import re as _re
from typing import TYPE_CHECKING, Any

from open_chat_shop.core.types import (
    Action,
    AgentMessage,
    SessionContext,
    UserMessage,
)

if TYPE_CHECKING:
    from open_chat_shop.core.orchestrator import DialogueOrchestrator

logger = logging.getLogger(__name__)


class ConfirmationResolver:
    """Resolves a persisted high-risk confirmation from the user's reply."""

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
    # "确认一下 / 看一下 / 核对一下" expresses a request to VERIFY, not consent —
    # the affirm token is part of a check-request. Treated as non-consent so a
    # reply like "我要先确认一下金额" does not execute the irreversible write
    # (audit: the substring affirm match accepted declarative non-consent).
    _VERIFY_HEDGE_RE = _re.compile(r"(确认|确定|核对|核实|看|检查|查|核)(一下|下)")

    def __init__(self, host: DialogueOrchestrator) -> None:
        self._host = host

    @staticmethod
    def _detect_affirmation(text: str) -> str | None:
        """Classify a confirmation reply as 'affirm', 'deny', or None.

        Deterministic rule match (Rule 5: code answers what code can). A
        non-affirmative reply never triggers the irreversible write. Explicit
        negations and question-form replies are both treated as non-consent.
        """
        stripped = text.strip()
        if ConfirmationResolver._DENY_RE.search(stripped):
            return "deny"
        # A clarifying/interrogative reply is not a "yes" — bail out before the
        # affirm match so "确定吗？" / "能确认下金额吗" do not execute the write.
        if ConfirmationResolver._QUESTION_RE.search(stripped):
            return None
        # A verify/check request ("确认一下金额") is not consent — bail out.
        if ConfirmationResolver._VERIFY_HEDGE_RE.search(stripped):
            return None
        if ConfirmationResolver._AFFIRM_RE.search(stripped):
            return "affirm"
        return None

    async def resolve(
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
        host = self._host
        signal = self._detect_affirmation(message.content)
        context.slots.pop("_pending_confirmation", None)

        if signal == "affirm":
            tool_name = pending.get("tool_name", "")
            tool = (
                host._tool_injector.get_tool(tool_name)
                if hasattr(host._tool_injector, "get_tool")
                else None
            )
            if tool is None:
                return host._error_response("抱歉，该操作已失效，请重新发起。")
            logger.info(
                "Pending confirmation accepted",
                extra={
                    **host._trace_extras(context.session_id),
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
            return await host._execute_action(action, context, [tool])

        if signal == "deny":
            logger.info(
                "Pending confirmation declined",
                extra={
                    **host._trace_extras(context.session_id),
                    "tool_name": pending.get("tool_name"),
                },
            )
            return host._error_response("好的，已为您取消该操作。")

        # Unrelated / ambiguous — discard and let normal classification run.
        return None
