"""Prometheus metrics for OpenChatShop.

Exposes counters, histograms, and gauges for chat requests, LLM calls,
tool invocations, cache hits, and session state.
"""
from __future__ import annotations

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

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


def get_metrics_content() -> bytes:
    """Return the latest Prometheus metrics exposition as bytes."""
    return generate_latest()


# ---------------------------------------------------------------------------
# ASGI metrics endpoint app
# ---------------------------------------------------------------------------

try:
    from starlette.responses import Response

    class _MetricsApp:
        """Minimal ASGI app that serves ``/metrics``."""

        async def __call__(
            self,
            scope: dict,
            receive: callable,  # type: ignore[type-arg]
            send: callable,  # type: ignore[type-arg]
        ) -> None:
            if scope["type"] == "http":
                body = generate_latest()
                response = Response(
                    content=body,
                    media_type=CONTENT_TYPE_LATEST,
                    status_code=200,
                )
                await response(scope, receive, send)

    metrics_app = _MetricsApp()
except ImportError:  # pragma: no cover — starlette unavailable in minimal envs
    metrics_app = None  # type: ignore[assignment]
