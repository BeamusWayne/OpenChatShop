"""Regression tests for H4 — Prometheus metric call-site instrumentation.

The metrics MODULE was correct but every counter/gauge was dead: nothing on the
request path called the record helpers, so /metrics, the alert rules, and
Grafana were non-functional. These tests assert the orchestrator and handoff
queue actually drive the metrics. They fail (no delta) before the call sites
are wired and pass after.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, ClassVar

from open_chat_shop.core.context import InMemoryContextManager
from open_chat_shop.core.handoff import HandoffQueue
from open_chat_shop.core.intent import CascadeIntentEngine, RuleBasedMatcher
from open_chat_shop.core.orchestrator import DialogueOrchestrator
from open_chat_shop.core.security import SecurityGuard
from open_chat_shop.core.strategy import RuleBasedStrategy
from open_chat_shop.core.tool import BaseTool, ToolInjector
from open_chat_shop.core.types import (
    Action,
    SessionContext,
    ToolPermission,
    ToolResult,
    UserMessage,
)
from open_chat_shop.observability.metrics import (
    CHAT_DURATION_SECONDS,
    CHAT_REQUESTS_TOTAL,
    HANDOFF_QUEUE_SIZE,
    LLM_CALLS_TOTAL,
    TOOL_CALLS_TOTAL,
)


def _counter_total(metric: Any) -> float:
    """Sum the value samples of a counter/histogram family across all labels."""
    total = 0.0
    for fam in metric.collect():
        for s in fam.samples:
            if s.name.endswith("_created"):
                continue
            if s.name.endswith("_total") or s.name.endswith("_count") or s.name.endswith("_sum"):
                total += s.value
    return total


def _gauge_value(metric: Any) -> float:
    for fam in metric.collect():
        for s in fam.samples:
            return float(s.value)
    return 0.0


def _build_orchestrator() -> DialogueOrchestrator:
    return DialogueOrchestrator(
        security_guard=SecurityGuard({}),
        context_manager=InMemoryContextManager(),
        intent_engine=CascadeIntentEngine(RuleBasedMatcher()),
        tool_injector=ToolInjector(registry={}, routing_rules=[]),
        strategy=RuleBasedStrategy(),
    )


class _MetricTool(BaseTool):
    name = "metric_tool"
    description = "test tool"
    category = "test"
    params_schema: ClassVar[dict] = {"type": "object", "properties": {}}
    permissions = ToolPermission(required_roles=["customer"])

    async def execute(self, params: dict, context: SessionContext) -> ToolResult:
        return ToolResult(success=True, data={"ok": True})


async def test_chat_request_and_duration_recorded() -> None:
    orch = _build_orchestrator()
    before_req = _counter_total(CHAT_REQUESTS_TOTAL)
    before_dur = _counter_total(CHAT_DURATION_SECONDS)  # histogram _count + _sum

    await orch.handle_message(
        UserMessage(session_id="m-1", content="你好", channel="web")
    )

    assert _counter_total(CHAT_REQUESTS_TOTAL) >= before_req + 1
    # histogram _count increments by 1 (its _sum also grows), so total grows by >= 1
    assert _counter_total(CHAT_DURATION_SECONDS) >= before_dur + 1


async def test_tool_call_recorded() -> None:
    orch = _build_orchestrator()
    before = _counter_total(TOOL_CALLS_TOTAL)

    action = Action(type="tool_call", payload={"tool_name": "metric_tool", "params": {}})
    ctx = SessionContext(session_id="t-1", user_id="user-001", channel="web")
    await orch._execute_tool(action, ctx, [_MetricTool()])

    assert _counter_total(TOOL_CALLS_TOTAL) >= before + 1


def test_llm_call_recorded() -> None:
    orch = _build_orchestrator()
    before = _counter_total(LLM_CALLS_TOTAL)

    response = SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=20, total_tokens=30)
    )
    orch._record_llm_cost(response)

    assert _counter_total(LLM_CALLS_TOTAL) >= before + 1


def test_handoff_queue_gauge_tracks_depth() -> None:
    from open_chat_shop.core.handoff import TransferRequest

    queue = HandoffQueue()
    queue.enqueue(TransferRequest(
        request_id="r-1", session_id="s-1", user_id="u-1", reason="test",
    ))
    assert _gauge_value(HANDOFF_QUEUE_SIZE) >= 1.0
