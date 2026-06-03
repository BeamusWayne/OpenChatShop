"""Tests for evaluation CLI — smoke tests for subcommands."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

# Project uses PYTHONPATH=src for imports
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_SRC_DIR = str(_PROJECT_ROOT / "src")
_BASE_ENV = {**os.environ, "PYTHONPATH": _SRC_DIR}


def _run_cli(*args: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    """Helper to invoke the evaluation CLI as a subprocess."""
    return subprocess.run(
        [sys.executable, "-m", "open_chat_shop.evaluation", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=_BASE_ENV,
    )


class TestListSubcommand:
    """Test the 'list' subcommand runs without error."""

    @pytest.mark.unit
    def test_list_runs_successfully(self) -> None:
        result = _run_cli("list")
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "Golden dataset:" in result.stdout
        assert "BO-001" in result.stdout

    @pytest.mark.unit
    def test_list_shows_sample_count(self) -> None:
        result = _run_cli("list")
        assert result.returncode == 0
        assert "samples" in result.stdout

    @pytest.mark.unit
    def test_list_displays_intent_column(self) -> None:
        result = _run_cli("list")
        assert result.returncode == 0
        assert "query_order" in result.stdout


class TestRegressionSubcommand:
    """Test the 'regression' subcommand logic in-process for speed."""

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_regression_scoring_on_result_tuple(self) -> None:
        """RegressionRunner *scoring* works on a hand-built result tuple.

        NOTE: this exercises only the scoring/report logic with a pre-filled
        actual_intent; it does NOT run the orchestrator and therefore cannot
        catch an extraction break. The real end-to-end guard is
        test_orchestrator_records_intent_on_meta below.
        """
        from open_chat_shop.evaluation.golden_dataset import get_golden_dataset
        from open_chat_shop.evaluation.regression import RegressionRunner

        dataset = get_golden_dataset()
        sample = dataset.get_by_id("BO-001")
        assert sample is not None

        runner = RegressionRunner(dataset)
        results = await runner.run_batch([
            (sample.sample_id, "query_order", {}, "您的订单已查询到", ["query_order"]),
        ])
        assert len(results) == 1
        report = runner.generate_report(results)
        assert report["total"] == 1
        assert "pass_rate" in report

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_orchestrator_records_intent_on_meta(self) -> None:
        """End-to-end guard for audit CRITICAL-4: the orchestrator must record
        the routing intent on response.meta, which is exactly what the
        regression harness reads. The original bug left actual_intent empty for
        every sample (0/500) because the harness read response.payload, which
        carries rich-message content rather than routing facts.
        """
        os.environ.setdefault("DEV_MODE", "true")
        from main import build_orchestrator

        from open_chat_shop.core.types import UserMessage
        from open_chat_shop.evaluation.golden_dataset import get_golden_dataset

        dataset = get_golden_dataset()
        sample = dataset.get_by_id("BO-001")
        assert sample is not None

        orchestrator = build_orchestrator()
        response = await orchestrator.handle_message(
            UserMessage(
                session_id="eval-cli-test",
                content=sample.user_input,
                channel="api",
            )
        )

        assert response.meta.get("intent_name"), (
            "orchestrator recorded no intent_name on meta — the regression "
            "harness would read an empty actual_intent (the 0/500 bug)"
        )

    @pytest.mark.unit
    def test_regression_import_does_not_error(self) -> None:
        """The __main__ module can be imported without errors."""
        from open_chat_shop.evaluation import __main__ as cli_mod

        assert hasattr(cli_mod, "main")
        assert hasattr(cli_mod, "_run_regression")
        assert hasattr(cli_mod, "_run_judge")
        assert hasattr(cli_mod, "_run_list")


class TestCLIHelp:
    """Test CLI help and error handling."""

    @pytest.mark.unit
    def test_no_subcommand_shows_error(self) -> None:
        result = _run_cli()
        assert result.returncode != 0

    @pytest.mark.unit
    def test_help_flag_works(self) -> None:
        result = _run_cli("--help")
        assert result.returncode == 0
        assert "evaluation" in result.stdout.lower() or "Evaluation" in result.stdout
