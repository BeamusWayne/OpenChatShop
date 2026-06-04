"""Shared pytest fixtures.

Prometheus metric isolation
---------------------------
The metrics in ``open_chat_shop.observability.metrics`` are module-level
singletons (one set of Counter/Histogram/Gauge objects per process). Counters
only ever go up, so their per-label values accumulate across every test in a
run. Two tests assert on *values* (not just presence):

  * ``test_audit_obs.py::test_record_helper_value_appears_in_exposition`` snaps
    a ``before`` value, increments once, and asserts the rendered exposition
    shows exactly ``before + 1``;
  * ``test_metrics_wiring.py`` snaps ``before`` totals and asserts ``>= before+1``.

When the full suite runs, *other* tests increment the same labelled series
between the snapshot and the assertion, so the first test intermittently sees a
value that is not ``before + 1`` and fails. The delta tests are more robust but
share the same global state.

This autouse fixture (scoped to the metric-sensitive modules) resets the
relevant collectors to a known-zero baseline before each such test, making the
value assertions deterministic regardless of suite ordering or what ran before.
It deliberately does NOT run for every test in the suite — only the modules that
assert on metric values — so it stays minimal and does not perturb tests that
rely on cumulative metric state elsewhere.

The multiprocess aggregation tests in ``test_audit_obs.py`` spawn fresh
subprocesses, so a reset in the parent process cannot affect them.
"""
from __future__ import annotations

from collections.abc import Iterator

import pytest

# Test modules whose assertions read metric *values* and therefore need a clean
# per-test baseline. Matched against the test node's module path basename.
_METRIC_SENSITIVE_MODULES = frozenset(
    {"test_metrics_wiring.py", "test_audit_obs.py"}
)


def _reset_metric_collectors() -> None:
    """Zero out the process-global metric collectors used by the value tests.

    Labelled families expose the public ``.clear()`` (drops every per-label
    child, so the next ``.labels(...)`` starts at 0). Unlabelled gauges have no
    label store and raise on ``.clear()``; they are reset with ``.set(0)``.
    """
    from open_chat_shop.observability import metrics

    labelled = (
        metrics.CHAT_REQUESTS_TOTAL,
        metrics.LLM_CALLS_TOTAL,
        metrics.LLM_TOKENS_TOTAL,
        metrics.LLM_COST_USD_TOTAL,
        metrics.TOOL_CALLS_TOTAL,
        metrics.CACHE_HITS_TOTAL,
        metrics.CHAT_DURATION_SECONDS,
    )
    for collector in labelled:
        collector.clear()

    unlabelled_gauges = (
        metrics.HANDOFF_QUEUE_SIZE,
        metrics.ACTIVE_SESSIONS,
    )
    for gauge in unlabelled_gauges:
        gauge.set(0)


@pytest.fixture(autouse=True)
def _isolate_prometheus_metrics(request: pytest.FixtureRequest) -> Iterator[None]:
    """Reset metric collectors before metric-value tests run.

    Autouse but inert for the rest of the suite: it only resets when the current
    test lives in one of ``_METRIC_SENSITIVE_MODULES``. This removes the shared
    global-counter flake without touching the individual tests' logic.
    """
    module_name = request.path.name
    if module_name in _METRIC_SENSITIVE_MODULES:
        _reset_metric_collectors()
    yield
