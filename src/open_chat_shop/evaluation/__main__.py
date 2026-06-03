"""Evaluation CLI — run regression tests, LLM judge, and list golden samples.

Usage:
    python -m open_chat_shop.evaluation regression
    python -m open_chat_shop.evaluation judge
    python -m open_chat_shop.evaluation list
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Any

from open_chat_shop.core.types import UserMessage
from open_chat_shop.evaluation.golden_dataset import get_golden_dataset
from open_chat_shop.evaluation.regression import RegressionRunner


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="open_chat_shop.evaluation",
        description="Evaluation tools for OpenChatShop",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("regression", help="Run regression against golden dataset")
    sub.add_parser("judge", help="Run LLM judge evaluation")
    sub.add_parser("list", help="List golden dataset samples")

    return parser


async def _run_regression() -> int:
    """Execute regression and return exit code (0=pass, 1=fail)."""
    dataset = get_golden_dataset()
    print(f"Loaded {len(dataset)} golden samples")

    from main import build_orchestrator

    orchestrator = build_orchestrator()
    runner = RegressionRunner(dataset)

    batch: list[tuple[str, str, dict, str, list[str]]] = []
    for sample in dataset._samples:
        msg = UserMessage(
            session_id=f"eval-{sample.sample_id}",
            content=sample.user_input,
            channel="api",
        )
        try:
            response = await orchestrator.handle_message(msg)
        except Exception as exc:
            print(f"  [{sample.sample_id}] ERROR: {exc}", file=sys.stderr)
            batch.append((sample.sample_id, "", {}, "", []))
            continue

        # Read routing facts from the structured meta the orchestrator records,
        # not from the channel payload (which holds rich-message content).
        meta = response.meta or {}
        actual_intent = meta.get("intent_name", "")
        actual_response = response.text_fallback
        actual_tool_calls: list[str] = list(meta.get("tool_calls", []))
        actual_entities: dict[str, Any] = dict(meta.get("entities", {}))

        batch.append((
            sample.sample_id,
            actual_intent,
            actual_entities,
            actual_response,
            actual_tool_calls,
        ))

    results = await runner.run_batch(batch)

    for r in results:
        status = "PASS" if r.passed else "FAIL"
        print(f"  [{r.sample_id}] {status}", end="")
        if not r.passed:
            print(f"  {'; '.join(r.errors)}", end="")
        print()

    report = runner.generate_report(results)
    print()
    print(json.dumps(report, indent=2, ensure_ascii=False))

    # Gate on intent_accuracy, which is independent of whether a real LLM is
    # configured. pass_rate additionally requires LLM-generated response text to
    # contain the golden keywords, so it is reported for visibility but only
    # meaningful when an LLM provider is available. This lets CI catch
    # intent-classification regressions without an API key.
    min_intent = float(os.environ.get("EVAL_MIN_INTENT_ACCURACY", "0.6"))
    intent_accuracy = report["intent_accuracy"]
    print(
        f"\nintent_accuracy={intent_accuracy} (gate >= {min_intent}); "
        f"pass_rate={report['pass_rate']} (requires LLM, informational)"
    )
    if intent_accuracy < min_intent:
        print(
            f"FAIL: intent_accuracy {intent_accuracy} < {min_intent}",
            file=sys.stderr,
        )
        return 1
    return 0


async def _run_judge() -> int:
    """Execute LLM judge evaluation and return exit code."""
    from main import build_orchestrator

    from open_chat_shop.evaluation.llm_judge import LLMJudge

    dataset = get_golden_dataset()
    print(f"Loaded {len(dataset)} golden samples")

    orchestrator = build_orchestrator()

    provider = orchestrator._provider
    if provider is None:
        print("ERROR: No LLM provider available for judge evaluation", file=sys.stderr)
        print("Set ANTHROPIC_API_KEY or configure a provider.", file=sys.stderr)
        return 1

    judge = LLMJudge(provider)
    all_passed = True

    for sample in dataset._samples:
        msg = UserMessage(
            session_id=f"judge-{sample.sample_id}",
            content=sample.user_input,
            channel="api",
        )
        try:
            response = await orchestrator.handle_message(msg)
        except Exception as exc:
            print(f"  [{sample.sample_id}] ERROR: {exc}", file=sys.stderr)
            continue

        results = await judge.evaluate(
            user_input=sample.user_input,
            agent_response=response.text_fallback,
        )

        print(f"  [{sample.sample_id}] ", end="")
        for r in results:
            mark = "PASS" if r.passed else "FAIL"
            print(f"{r.dimension}={r.score}({mark}) ", end="")
            if not r.passed:
                all_passed = False
        print()

    return 0 if all_passed else 1


def _run_list() -> int:
    """Print all golden samples and return exit code 0."""
    dataset = get_golden_dataset()
    print(f"Golden dataset: {len(dataset)} samples\n")
    print(f"{'ID':<10} {'Intent':<30} {'User Input'}")
    print("-" * 70)
    for sample in dataset._samples:
        display_input = sample.user_input[:40]
        if len(sample.user_input) > 40:
            display_input += "..."
        print(f"{sample.sample_id:<10} {sample.intent:<30} {display_input}")
    return 0


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "list":
        sys.exit(_run_list())
    elif args.command == "regression":
        sys.exit(asyncio.run(_run_regression()))
    elif args.command == "judge":
        sys.exit(asyncio.run(_run_judge()))


if __name__ == "__main__":
    main()
