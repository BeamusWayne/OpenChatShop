"""Prometheus metrics for OpenChatShop.

Exposes counters, histograms, and gauges for chat requests, LLM calls,
tool invocations, cache hits, and session state.

Multiprocess deployments
-------------------------
Under gunicorn the app runs ``workers = CPU*2+1`` processes that each get
their own copy of the module-level metric objects. With the default
single-process registry, ``generate_latest()`` returns only the slice of
the worker that happened to serve the scrape, so totals appear to jump and
counters undercount by ~1/N.

To get correct aggregation, set ``PROMETHEUS_MULTIPROC_DIR`` to a writable
(tmpfs) directory **before** ``prometheus_client`` is imported. When that
env var is present, :func:`get_metrics_content` (and the mounted
``/metrics`` ASGI app) build a fresh ``CollectorRegistry`` backed by a
``MultiProcessCollector`` that merges every worker's on-disk samples, so a
single scrape reflects the whole process group.

The gunicorn ``child_exit`` hook should call :func:`mark_process_dead`
(re-exported here) so a dead worker's gauge files are cleaned up.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    multiprocess,
)
from prometheus_client.multiprocess import mark_process_dead
from prometheus_client.values import get_value_class

__all__ = [
    "ACTIVE_SESSIONS",
    "CACHE_HITS_TOTAL",
    "CHAT_DURATION_SECONDS",
    "CHAT_REQUESTS_TOTAL",
    "CONTENT_TYPE_LATEST",
    "HANDOFF_QUEUE_SIZE",
    "LLM_CALLS_TOTAL",
    "LLM_COST_USD_TOTAL",
    "LLM_TOKENS_TOTAL",
    "TOOL_CALLS_TOTAL",
    "get_metrics_content",
    "mark_process_dead",
    "metrics_app",
    "multiprocess_enabled",
    "observe_chat_duration",
    "record_cache_hit",
    "record_chat_request",
    "record_llm_call",
    "record_tool_call",
]

# ---------------------------------------------------------------------------
# Counters
# ---------------------------------------------------------------------------

CHAT_REQUESTS_TOTAL = Counter(
    "openchatshop_chat_requests_total",
    "Total number of chat requests processed.",
    ["intent", "status"],
)

LLM_CALLS_TOTAL = Counter(
    "openchatshop_llm_calls_total",
    "Total number of LLM API calls.",
    ["model", "status"],
)

LLM_TOKENS_TOTAL = Counter(
    "openchatshop_llm_tokens_total",
    "Total number of LLM tokens consumed.",
    ["model", "type"],
)

LLM_COST_USD_TOTAL = Counter(
    "openchatshop_llm_cost_usd_total",
    "Total LLM cost in USD.",
    ["model"],
)

TOOL_CALLS_TOTAL = Counter(
    "openchatshop_tool_calls_total",
    "Total number of tool calls.",
    ["tool", "status"],
)

CACHE_HITS_TOTAL = Counter(
    "openchatshop_cache_hits_total",
    "Total number of intent cache hits.",
    ["intent"],
)

# ---------------------------------------------------------------------------
# Histograms
# ---------------------------------------------------------------------------

CHAT_DURATION_SECONDS = Histogram(
    "openchatshop_chat_duration_seconds",
    "Chat request duration in seconds.",
    ["intent"],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

# ---------------------------------------------------------------------------
# Gauges
# ---------------------------------------------------------------------------

ACTIVE_SESSIONS = Gauge(
    "openchatshop_active_sessions",
    "Number of currently active sessions.",
)

HANDOFF_QUEUE_SIZE = Gauge(
    "openchatshop_handoff_queue_size",
    "Number of sessions waiting in the human-agent handoff queue.",
)

# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------


def record_chat_request(intent: str, status: str) -> None:
    """Increment the chat request counter."""
    CHAT_REQUESTS_TOTAL.labels(intent=intent, status=status).inc()


def observe_chat_duration(intent: str, duration: float) -> None:
    """Record a chat request latency observation."""
    CHAT_DURATION_SECONDS.labels(intent=intent).observe(duration)


def record_llm_call(
    model: str,
    status: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    cost_usd: float = 0.0,
) -> None:
    """Increment LLM call counter and optionally record tokens and cost."""
    LLM_CALLS_TOTAL.labels(model=model, status=status).inc()
    if prompt_tokens:
        LLM_TOKENS_TOTAL.labels(model=model, type="prompt").inc(prompt_tokens)
    if completion_tokens:
        LLM_TOKENS_TOTAL.labels(model=model, type="completion").inc(completion_tokens)
    if cost_usd:
        LLM_COST_USD_TOTAL.labels(model=model).inc(cost_usd)


def record_tool_call(tool: str, status: str) -> None:
    """Increment the tool call counter."""
    TOOL_CALLS_TOTAL.labels(tool=tool, status=status).inc()


def record_cache_hit(intent: str) -> None:
    """Increment the cache hit counter."""
    CACHE_HITS_TOTAL.labels(intent=intent).inc()


# ---------------------------------------------------------------------------
# Multiprocess-aware rendering
# ---------------------------------------------------------------------------


def multiprocess_enabled() -> bool:
    """Return True when ``prometheus_client`` is in multiprocess mode.

    Mirrors how ``prometheus_client`` itself decides: the multiprocess value
    class is only selected when ``PROMETHEUS_MULTIPROC_DIR`` is set at import
    time. Checking the live value class (rather than re-reading the env var)
    means we never try to aggregate from a directory the metric objects were
    not actually writing to.
    """
    # get_value_class returns the live value *class* whose ``_multiprocess``
    # class attribute is True only when PROMETHEUS_MULTIPROC_DIR was set at the
    # time the first metric was constructed. It is untyped upstream.
    value_class = get_value_class()  # type: ignore[no-untyped-call]
    return bool(getattr(value_class, "_multiprocess", False))


def _build_registry() -> CollectorRegistry:
    """Return a registry to serialize from.

    In multiprocess mode this is a fresh registry fed by a
    ``MultiProcessCollector`` that merges every worker's on-disk samples, so a
    single scrape reflects the whole gunicorn process group instead of just
    the worker that answered. Otherwise the default global registry is used.
    """
    if multiprocess_enabled():
        registry = CollectorRegistry()
        # MultiProcessCollector registers itself with the registry as a side
        # effect; it is untyped upstream.
        multiprocess.MultiProcessCollector(registry)  # type: ignore[no-untyped-call]
        return registry
    return REGISTRY


def get_metrics_content() -> bytes:
    """Return the latest Prometheus metrics exposition as bytes.

    Aggregates across all workers when multiprocess mode is active (see the
    module docstring), otherwise serializes the local process registry.
    """
    return generate_latest(_build_registry())


# ---------------------------------------------------------------------------
# ASGI metrics endpoint app
# ---------------------------------------------------------------------------

try:
    from starlette.responses import Response

    class _MetricsApp:
        """Minimal ASGI app that serves ``/metrics``."""

        async def __call__(
            self,
            scope: dict[str, Any],
            receive: Callable[..., Any],
            send: Callable[..., Any],
        ) -> None:
            if scope["type"] == "http":
                body = get_metrics_content()
                response = Response(
                    content=body,
                    media_type=CONTENT_TYPE_LATEST,
                    status_code=200,
                )
                await response(scope, receive, send)

    metrics_app = _MetricsApp()
except ImportError:  # pragma: no cover — starlette unavailable in minimal envs
    metrics_app = None  # type: ignore[assignment]
