"""OpenTelemetry tracing integration for CommerceAgent.

Implements contracts.md §14.2 — 10 trace spans covering the critical
path of the agent's request handling pipeline.
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any, Iterator

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_tracer: trace.Tracer | None = None

# ---------------------------------------------------------------------------
# Setup helpers
# ---------------------------------------------------------------------------


def setup_tracing(
    service_name: str = "commerce-agent",
    endpoint: str | None = None,
) -> trace.Tracer:
    """Create and install a global :class:`TracerProvider`.

    Parameters
    ----------
    service_name:
        Logical service name attached to every span.
    endpoint:
        If provided, an ``OTLPSpanExporter`` is wired in.  When *None*
        (the default) a ``ConsoleSpanExporter`` is used so that spans
        appear on stdout during development.
    """
    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)

    if endpoint is not None:
        # Lazy import — opentelemetry-exporter-otlp may not be installed.
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )

        exporter = OTLPSpanExporter(endpoint=endpoint)
    else:
        exporter = ConsoleSpanExporter()

    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    global _tracer  # noqa: PLW0603
    _tracer = trace.get_tracer(service_name)
    return _tracer


def get_tracer() -> trace.Tracer:
    """Return the global tracer.

    Lazily initialises a default tracer (console exporter) if
    :func:`setup_tracing` has not been called yet.
    """
    global _tracer  # noqa: PLW0603
    if _tracer is None:
        _tracer = setup_tracing()
    return _tracer


# ---------------------------------------------------------------------------
# Internal helper — common span context manager
# ---------------------------------------------------------------------------


@contextmanager
def _span(
    name: str,
    attributes: dict[str, Any] | None = None,
) -> Iterator[trace.Span]:
    """Yield an active span with automatic duration and exception recording."""
    tracer = get_tracer()
    span = tracer.start_span(name, attributes=attributes)
    start = time.monotonic()
    with trace.use_span(span, end_on_exit=True):
        try:
            yield span
        except Exception as exc:
            span.set_status(trace.StatusCode.ERROR)
            span.record_exception(exception=exc)
            raise
        finally:
            elapsed_ms = (time.monotonic() - start) * 1000
            span.set_attribute("duration_ms", round(elapsed_ms, 3))


# ---------------------------------------------------------------------------
# Public span helpers — one per contracts §14.2 operation
# ---------------------------------------------------------------------------


@contextmanager
def trace_orchestrator_handle(session_id: str) -> Iterator[trace.Span]:
    """Span ``orchestrator.handle_message``."""
    with _span(
        "orchestrator.handle_message",
        {"service.name": "commerce-agent", "session_id": session_id},
    ) as span:
        yield span


@contextmanager
def trace_provider_chat(model: str) -> Iterator[trace.Span]:
    """Span ``provider.chat``."""
    with _span(
        "provider.chat",
        {"service.name": "commerce-agent", "model": model},
    ) as span:
        yield span


@contextmanager
def trace_provider_cascade(models: list[str]) -> Iterator[trace.Span]:
    """Span ``provider.cascade``."""
    with _span(
        "provider.cascade",
        {
            "service.name": "commerce-agent",
            "models": ",".join(models),
            "model_count": len(models),
        },
    ) as span:
        yield span


@contextmanager
def trace_context_load(session_id: str) -> Iterator[trace.Span]:
    """Span ``context.load``."""
    with _span(
        "context.load",
        {"service.name": "commerce-agent", "session_id": session_id},
    ) as span:
        yield span


@contextmanager
def trace_context_compress(before_tokens: int) -> Iterator[trace.Span]:
    """Span ``context.compress``."""
    with _span(
        "context.compress",
        {"service.name": "commerce-agent", "before_tokens": before_tokens},
    ) as span:
        yield span


@contextmanager
def trace_intent_classify(source: str) -> Iterator[trace.Span]:
    """Span ``intent.classify``."""
    with _span(
        "intent.classify",
        {"service.name": "commerce-agent", "source": source},
    ) as span:
        yield span


@contextmanager
def trace_tool_inject(intent: str) -> Iterator[trace.Span]:
    """Span ``tool.inject``."""
    with _span(
        "tool.inject",
        {"service.name": "commerce-agent", "intent": intent},
    ) as span:
        yield span


@contextmanager
def trace_tool_execute(tool_name: str) -> Iterator[trace.Span]:
    """Span ``tool.execute``."""
    with _span(
        "tool.execute",
        {"service.name": "commerce-agent", "tool_name": tool_name},
    ) as span:
        yield span


@contextmanager
def trace_security_check() -> Iterator[trace.Span]:
    """Span ``security.check``."""
    with _span(
        "security.check",
        {"service.name": "commerce-agent"},
    ) as span:
        yield span


@contextmanager
def trace_channel_adapt(
    channel: str,
    original_type: str,
) -> Iterator[trace.Span]:
    """Span ``channel.adapt``."""
    with _span(
        "channel.adapt",
        {
            "service.name": "commerce-agent",
            "channel": channel,
            "original_type": original_type,
        },
    ) as span:
        yield span
