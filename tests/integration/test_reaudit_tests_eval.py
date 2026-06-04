"""Re-audit cluster ``tests_eval`` — regression coverage for three gaps.

The re-audit flagged three places where the eval / pipeline lacked teeth:

(2) ``evaluation/__main__._run_regression`` — the full 500-sample regression +
    intent-accuracy + attack-security gate — was only ever run by the manual CLI
    and CI, never by pytest. A break in the orchestrator-to-gate wiring (e.g. the
    exit code no longer reflecting the intent/security gates) would ship green.
    Here we invoke the REAL ``_run_regression`` end to end and pin BOTH gate
    outcomes deterministically by varying ``EVAL_MIN_INTENT_ACCURACY``.

(3a) The pipeline was tested against the DB backend only for the double-persist
    seam (``test_db_orchestrator_seam.py``), which wires an EMPTY tool registry —
    no tool ever runs. This complements it: the full pipeline executes real
    builtin tools while persisting to ``DatabaseContextManager``, proving tool
    turns round-trip exactly once on the DB path too.

(3b) The "attack executes zero tools" guarantee was only asserted with
    ``provider=None`` (keyless CI). This asserts it ALSO holds on the
    LLM-function-calling path: with a provider installed that actively returns a
    ``query_order`` tool_call (simulating the model choosing the attacker's
    tool), every attack sample STILL executes zero tools. A positive control
    proves a benign query DOES reach the tool, so the zero-tool result is a real
    security property, not a dead route.
"""
from __future__ import annotations

import importlib.util
import logging
import os
from pathlib import Path
from typing import Any

import pytest

from open_chat_shop.core.context import InMemoryContextManager
from open_chat_shop.core.intent import (
    CascadeIntentEngine,
    IntentInfo,
    RuleBasedMatcher,
)
from open_chat_shop.core.orchestrator import DialogueOrchestrator
from open_chat_shop.core.security import SecurityGuard
from open_chat_shop.core.strategy import RuleBasedStrategy
from open_chat_shop.core.tool import ToolInjector
from open_chat_shop.core.types import (
    LLMResponse,
    RoutingRule,
    TokenUsage,
    ToolCall,
    UserMessage,
)
from open_chat_shop.evaluation.golden_dataset import get_golden_dataset
from open_chat_shop.storage.db_context import DatabaseContextManager
from open_chat_shop.tools.builtin import create_tools

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_pipeline_builder() -> Any:
    """Import the real fully-wired orchestrator factory from test_pipeline.

    Reusing it (rather than re-declaring the wiring) keeps this test honest: it
    exercises the same real-module pipeline the integration suite already trusts.
    """
    spec = importlib.util.spec_from_file_location(
        "_pipeline_helper",
        _PROJECT_ROOT / "tests" / "integration" / "test_pipeline.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.build_orchestrator


# ---------------------------------------------------------------------------
# (2) The real _run_regression gate is exercised by pytest.
# ---------------------------------------------------------------------------


def _run_regression_with_intent_gate(min_intent: str) -> int:
    """Invoke the REAL evaluation CLI ``_run_regression`` and return its exit code.

    Forces rule-only routing (``_build_provider`` -> None) so the run is
    deterministic and keyless — the exact condition CI uses. ``min_intent`` sets
    the intent-accuracy gate threshold for this invocation. Restores patched
    globals afterwards so the shared ``main`` module is left untouched.
    """
    import asyncio

    os.environ.setdefault("DEV_MODE", "true")
    import main

    from open_chat_shop.evaluation import __main__ as cli

    original_build_provider = main._build_provider
    original_min = os.environ.get("EVAL_MIN_INTENT_ACCURACY")
    main._build_provider = lambda: None
    os.environ["EVAL_MIN_INTENT_ACCURACY"] = min_intent
    logging.disable(logging.CRITICAL)
    try:
        return asyncio.run(cli._run_regression())
    finally:
        main._build_provider = original_build_provider
        logging.disable(logging.NOTSET)
        if original_min is None:
            os.environ.pop("EVAL_MIN_INTENT_ACCURACY", None)
        else:
            os.environ["EVAL_MIN_INTENT_ACCURACY"] = original_min


@pytest.mark.integration
def test_run_regression_passes_when_intent_gate_met(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The full pipeline + security gate returns 0 when the intent gate is met.

    Rule-only intent accuracy is ~0.47, so a gate of 0.4 is satisfied. Reaching
    exit 0 means: all 500 samples ran through the live orchestrator, the
    attack-security gate found ZERO tools executed across the attack set, and the
    intent gate passed — the whole ``_run_regression`` body executed, not a mock.
    """
    rc = _run_regression_with_intent_gate("0.4")
    out = capsys.readouterr().out
    assert rc == 0, f"expected pass at gate 0.4; output tail:\n{out[-800:]}"
    # The security gate must have actually run over the attack set with no tool
    # execution — this is the LLM-independent guarantee the gate enforces.
    assert "attack_security:" in out
    assert "tools_executed=0" in out, (
        "the regression's attack-security gate did not confirm zero tool "
        "executions — security teeth missing from the real run"
    )


@pytest.mark.integration
def test_run_regression_fails_when_intent_gate_not_met(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Exit code is wired to the intent gate: an unmet threshold returns 1.

    With the production default gate (0.6) and rule-only routing (~0.47), the run
    must fail. This pins that ``_run_regression`` actually enforces the gate via
    its return code — a regression that always returned 0 (gate defanged) fails
    this test.
    """
    rc = _run_regression_with_intent_gate("0.6")
    captured = capsys.readouterr()
    assert rc == 1, (
        f"expected gate failure at 0.6; stdout tail:\n{captured.out[-800:]}"
    )
    # The gate decision is reported on stdout; the FAIL line goes to stderr.
    assert "(gate >= 0.6)" in captured.out
    assert "FAIL: intent_accuracy" in captured.err


# ---------------------------------------------------------------------------
# (3a) Pipeline executes real tools while persisting to the DB backend.
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_pipeline_tool_turns_persist_once_on_db_backend() -> None:
    """Full pipeline + real tools + DatabaseContextManager: each turn persists once.

    Complements ``test_db_orchestrator_seam.py`` (which wires an EMPTY registry,
    so no tool runs): here every turn actually executes a builtin tool, and the
    DB-backed history must still contain exactly one user + one assistant row per
    turn — no double-persist on the tool path.
    """
    build_orchestrator = _load_pipeline_builder()
    orch = build_orchestrator()
    db = DatabaseContextManager(db_url="sqlite:///:memory:")
    # The pipeline factory wires real modules; swap only the context backend so
    # we drive the SAME real tool/route/strategy stack against the DB.
    orch._context_manager = db

    sid = "reaudit-db-tools"
    r1 = await orch.handle_message(
        UserMessage(session_id=sid, content="搜索商品 keyboard", channel="web")
    )
    r2 = await orch.handle_message(
        UserMessage(session_id=sid, content="查询订单 ORD-001", channel="web")
    )

    # Both turns really executed a tool (otherwise this would not exercise the
    # tool path on the DB backend at all).
    assert (r1.meta or {}).get("tool_calls") == ["search_product"], r1.meta
    assert (r2.meta or {}).get("tool_calls") == ["query_order"], r2.meta

    reloaded = await db.load(sid)
    user_turns = [m for m in reloaded.history if m.role == "user"]
    asst_turns = [m for m in reloaded.history if m.role == "assistant"]
    assert len(user_turns) == 2, [m.content for m in reloaded.history]
    assert len(asst_turns) == 2, [m.content for m in reloaded.history]
    assert len(reloaded.history) == 4


@pytest.mark.integration
@pytest.mark.asyncio
async def test_db_and_inmemory_tool_history_agree() -> None:
    """A tool-executing conversation round-trips identically on DB and InMemory.

    The seam regression compared empty-registry histories; this compares the
    TOOL path so a future DB-only divergence in how tool turns are stored is
    caught.
    """
    build_orchestrator = _load_pipeline_builder()
    turns = ("搜索商品 keyboard", "查询订单 ORD-001")

    db = DatabaseContextManager(db_url="sqlite:///:memory:")
    od = build_orchestrator()
    od._context_manager = db
    for c in turns:
        await od.handle_message(UserMessage(session_id="cmp", content=c, channel="web"))
    db_hist = [(m.role, m.content) for m in (await db.load("cmp")).history]

    mem = InMemoryContextManager()
    om = build_orchestrator()
    om._context_manager = mem
    for c in turns:
        await om.handle_message(UserMessage(session_id="cmp", content=c, channel="web"))
    mem_hist = [(m.role, m.content) for m in (await mem.load("cmp")).history]

    assert db_hist == mem_hist, f"DB={db_hist} != InMemory={mem_hist}"


# ---------------------------------------------------------------------------
# (3b) Attack zero-tool gate holds on the LLM-function-calling path.
# ---------------------------------------------------------------------------


class _ToolReturningSpyProvider:
    """A provider that records calls and actively asks to run ``query_order``.

    This simulates an LLM on the native function-calling path *choosing* the
    attacker's tool. The orchestrator must never act on this for an attack —
    proving the security/routing layer, not the provider, decides tool execution.
    """

    def __init__(self) -> None:
        self.call_count = 0

    async def chat(
        self, messages: list[Any], tools: list[Any] | None = None
    ) -> LLMResponse:
        self.call_count += 1
        return LLMResponse(
            content="（模型生成的回复）",
            tool_calls=[
                ToolCall(tool_name="query_order", params={"order_id": "X"}, call_id="c1")
            ],
            usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            finish_reason="tool_calls",
        )


def _orchestrator_with_live_tool_route(
    provider: _ToolReturningSpyProvider,
) -> DialogueOrchestrator:
    """Wire real builtin tools + a query_order route + a tool-returning provider.

    With the route present, an UN-neutralized attack WOULD reach ``query_order``;
    with the spy provider installed, the LLM-function-calling path is live. So a
    zero-tool result is a genuine security guarantee, not an artifact of there
    being no tool to run.
    """
    registry = {t.name: t for t in create_tools()}
    rules = [RoutingRule(intent_patterns=["query_order"], tools=["query_order"])]
    matcher = RuleBasedMatcher()
    # A real query_order intent rule so the POSITIVE control can classify + route.
    matcher.add_rule("query_order", r"查询.*订单|查订单|订单.*状态|order")
    engine = CascadeIntentEngine(matcher, level1_threshold=0.85)
    engine.register_intent(
        IntentInfo(
            name="query_order",
            display_name="查询订单",
            description="查询订单",
            sample_count=5,
        )
    )
    orch = DialogueOrchestrator(
        security_guard=SecurityGuard({}),
        context_manager=InMemoryContextManager(),
        intent_engine=engine,
        tool_injector=ToolInjector(registry=registry, routing_rules=rules),
        strategy=RuleBasedStrategy(),
    )
    orch.set_provider(provider)
    return orch


@pytest.mark.integration
@pytest.mark.asyncio
async def test_attack_zero_tool_gate_holds_with_llm_provider() -> None:
    """Every attack executes ZERO tools even with a tool-returning provider live.

    RED if the orchestrator ever acted on the provider's ``query_order``
    tool_call for an attack (or if the security layer were bypassed on the
    provider path). The provider IS consulted for the attacks the security layer
    does not pre-block (their fallback reply is LLM-enhanced), so the LLM path is
    genuinely on — yet no attack reaches a tool.
    """
    logging.disable(logging.CRITICAL)
    try:
        provider = _ToolReturningSpyProvider()
        orch = _orchestrator_with_live_tool_route(provider)
        dataset = get_golden_dataset()
        attacks = dataset.get_by_scenario_type("attack")
        assert len(attacks) >= 8

        provider_consulted = 0
        for sample in attacks:
            before = provider.call_count
            response = await orch.handle_message(
                UserMessage(
                    session_id=f"reaudit-fc-{sample.sample_id}",
                    content=sample.user_input,
                    channel="web",
                )
            )
            tool_calls = (response.meta or {}).get("tool_calls") or []
            assert tool_calls == [], (
                f"{sample.sample_id} executed a tool on the LLM-FC path: "
                f"{tool_calls}; the model returned a query_order tool_call and "
                "the orchestrator must NOT act on it for an attack"
            )
            assert response.message_type == "text", (
                f"{sample.sample_id} produced a {response.message_type} response, "
                "not a plain refusal/fallback"
            )
            if provider.call_count > before:
                provider_consulted += 1
    finally:
        logging.disable(logging.NOTSET)

    # Teeth check: the provider (LLM path) really was exercised for at least some
    # attacks — so the zero-tool result above is NOT just because the provider
    # was never reached. The check_input-blocked attacks short-circuit earlier;
    # the rest are LLM-enhanced fallbacks.
    assert provider_consulted >= 1, (
        "no attack reached the provider — the LLM-function-calling path was "
        "never exercised, so the zero-tool assertion proves nothing"
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_benign_query_does_reach_tool_with_llm_provider() -> None:
    """Positive control: a legitimate order query DOES execute query_order.

    Proves the tool route is live under the same wiring, so the attack test's
    zero-tool outcome is a real security property rather than a dead path.
    """
    logging.disable(logging.CRITICAL)
    try:
        provider = _ToolReturningSpyProvider()
        orch = _orchestrator_with_live_tool_route(provider)
        response = await orch.handle_message(
            UserMessage(
                session_id="reaudit-fc-benign",
                content="查询订单 ORD-001",
                channel="web",
            )
        )
    finally:
        logging.disable(logging.NOTSET)

    assert (response.meta or {}).get("tool_calls") == ["query_order"], response.meta
