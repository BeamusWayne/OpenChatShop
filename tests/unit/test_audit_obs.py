
# orchestrator (test_audit_<CLUSTER>.py, CLUSTER=OBS); keep the uppercase name.
"""Audit regression tests — cluster OBS (Prometheus observability).

Covers the two HIGH findings:

1. The metrics module exposes clean, working record helpers (so /metrics can
   serve real, non-zero data once call sites are wired by the orchestrator
   owner). Verified here by recording through the public helpers and asserting
   the value lands in the exposition.

2. Multiprocess-safety: under gunicorn (workers = CPU*2+1, preload_app), each
   worker holds its own metric copies. The previous ``get_metrics_content`` /
   ``/metrics`` app called ``generate_latest()`` with no registry, so a scrape
   returned only the answering worker's slice — counters undercounted by ~1/N
   and oscillated between scrapes. The fix builds a fresh registry fed by a
   ``MultiProcessCollector`` when ``PROMETHEUS_MULTIPROC_DIR`` is set, merging
   every worker's on-disk samples into one scrape.

   RED before fix: a counter written into the multiprocess dir by a *different*
   process is absent from ``get_metrics_content()`` (default registry only).
   GREEN after fix: that value appears, because the output aggregates the dir.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path


def test_record_helper_value_appears_in_exposition() -> None:
    """Public record helper must produce a non-zero sample in the output.

    This is the "metrics are recordable / not dead" guarantee from finding #1.
    A bare "name is present" check passes even on an all-zero exposition, so we
    assert the *incremented value* is rendered.
    """
    from open_chat_shop.observability.metrics import (
        TOOL_CALLS_TOTAL,
        get_metrics_content,
        record_tool_call,
    )

    before = TOOL_CALLS_TOTAL.labels(tool="audit_obs_probe", status="ok")._value.get()
    record_tool_call("audit_obs_probe", "ok")
    text = get_metrics_content().decode("utf-8")

    expected = before + 1.0
    # prometheus may render the float as "1.0" or "1"; match the labelled line.
    line = 'openchatshop_tool_calls_total{status="ok",tool="audit_obs_probe"}'
    assert line in text
    assert (
        f"{line} {expected}" in text or f"{line} {int(expected)}" in text
    ), f"expected incremented value {expected} for {line} in:\n{text}"


def test_multiprocess_enabled_false_without_env() -> None:
    """Without PROMETHEUS_MULTIPROC_DIR the module reports single-process mode."""
    from open_chat_shop.observability import metrics

    # The test runner process is started without the env var set.
    assert metrics.multiprocess_enabled() is False


def test_mark_process_dead_is_exported() -> None:
    """The gunicorn child_exit hook needs a clean handle to clean up dead workers."""
    from open_chat_shop.observability import metrics

    assert callable(metrics.mark_process_dead)
    assert "mark_process_dead" in metrics.__all__


# --- Two-process aggregation probe -----------------------------------------
#
# Within a *single* process the in-memory Counter still reports its value via
# the default registry, so a one-process test cannot tell old code from new.
# The bug only bites across distinct gunicorn workers: worker A increments and
# exits, then a scrape served by worker B (which never touched that counter)
# must still surface A's value. That only works through MultiProcessCollector
# reading the shared dir — exactly what get_metrics_content now does.

# Writer: sets the dir before importing prometheus, increments, exits (flushing
# the sample to a .db file in the shared dir).
_WRITER = """
import os, sys
os.environ["PROMETHEUS_MULTIPROC_DIR"] = sys.argv[1]
from prometheus_client import Counter
c = Counter("audit_obs_mp_total", "probe", ["worker"])
c.labels(worker="w1").inc(7)
"""

# Reader: a DIFFERENT process that never increments the counter. It renders via
# the project's get_metrics_content(). Pre-fix (plain generate_latest) -> MISS;
# post-fix (MultiProcessCollector over the dir) -> FOUND.
_READER = """
import os, sys
os.environ["PROMETHEUS_MULTIPROC_DIR"] = sys.argv[1]
from open_chat_shop.observability.metrics import (
    get_metrics_content,
    multiprocess_enabled,
)
assert multiprocess_enabled() is True, "env set at import => multiprocess mode"
out = get_metrics_content().decode("utf-8")
sys.stdout.write("FOUND" if 'audit_obs_mp_total{worker="w1"}' in out else "MISSING")
"""


def _run(probe: str, mp_dir: str, src: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", probe, mp_dir],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "PYTHONPATH": src},
        timeout=60,
        check=False,
    )


def test_metrics_aggregate_across_worker_processes() -> None:
    """A scrape must merge samples a *different* worker wrote to the shared dir.

    RED before fix: get_metrics_content used the default registry, so the
    reader process (which never incremented) printed MISSING.
    GREEN after fix: MultiProcessCollector merges the writer's .db file.
    """
    src = str(Path(__file__).resolve().parents[2] / "src")
    with tempfile.TemporaryDirectory() as mp_dir:
        writer = _run(_WRITER, mp_dir, src)
        assert writer.returncode == 0, f"writer failed: {writer.stderr}"
        assert any(Path(mp_dir).iterdir()), "writer left no multiprocess .db file"

        reader = _run(_READER, mp_dir, src)
        assert reader.returncode == 0, (
            f"reader failed: rc={reader.returncode}\n"
            f"stdout={reader.stdout}\nstderr={reader.stderr}"
        )
        assert reader.stdout.strip() == "FOUND", (
            "cross-worker aggregation missing — get_metrics_content did not "
            f"merge another process's samples. stdout={reader.stdout!r} "
            f"stderr={reader.stderr!r}"
        )
