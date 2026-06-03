"""OpenTelemetry tracing integration for OpenChatShop.

Implements contracts.md §14.2 — 10 trace spans covering the critical
path of the agent's request handling pipeline.
"""
from __future__ import annotations

import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_tracer: trace.Tracer | None = None

_CONSOLE_ENV_TRUE = frozenset({"1", "true", "yes"})

# ---------------------------------------------------------------------------
# Setup helpers
# ---------------------------------------------------------------------------


def _console_enabled(console: bool | None) -> bool:
    """Resolve whether to install the console exporter (explicit arg > env)."""
    if console is not None:
        return console
    return os.environ.get("OTEL_CONSOLE_EXPORT", "").strip().lower() in _CONSOLE_ENV_TRUE


def setup_tracing(
    service_name: str = "open-chat-shop",
    endpoint: str | None = None,
    console: bool | None = None,
) -> trace.Tracer:
    """Create and install a global :class:`TracerProvider`.

    Parameters
    ----------
    service_name:
        Logical service name attached to every span.
    endpoint:
        If provided, an ``OTLPSpanExporter`` is wired in.
    console:
        If True, spans are exported to stdout via ``ConsoleSpanExporter``.
        When *None* (the default) this is read from the
        ``OTEL_CONSOLE_EXPORT`` environment variable.  Default **off** — by
        default no exporter is installed, so spans are created but never
        exported; tracing then adds no stdout noise or per-span export
        latency (notably during evaluation runs over hundreds of samples).
    """
    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)

    console = _console_enabled(console)

    if endpoint is not None:
        # Lazy import — opentelemetry-exporter-otlp may not be installed.
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )

        provider.add_span_processor(
            SimpleSpanProcessor(OTLPSpanExporter(endpoint=endpoint))
        )
    elif console:
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    # else: no exporter installed — spans are created but never exported.

    trace.set_tracer_provider(provider)

    global _tracer
    _tracer = trace.get_tracer(service_name)
    return _tracer


def get_tracer() -> trace.Tracer:
    """Return the global tracer.

    Lazily initialises a default tracer (no exporter — quiet) if
    :func:`setup_tracing` has not been called yet.
    """
    global _tracer
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
        {"service.name": "open-chat-shop", "session_id": session_id},
    ) as span:
        yield span


@contextmanager
def trace_provider_chat(model: str) -> Iterator[trace.Span]:
    """Span ``provider.chat``."""
    with _span(
        "provider.chat",
        {"service.name": "open-chat-shop", "model": model},
    ) as span:
        yield span


@contextmanager
def trace_provider_cascade(models: list[str]) -> Iterator[trace.Span]:
    """Span ``provider.cascade``."""
    with _span(
        "provider.cascade",
        {
            "service.name": "open-chat-shop",
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
        {"service.name": "open-chat-shop", "session_id": session_id},
    ) as span:
        yield span


@contextmanager
def trace_context_compress(before_tokens: int) -> Iterator[trace.Span]:
    """Span ``context.compress``."""
    with _span(
        "context.compress",
        {"service.name": "open-chat-shop", "before_tokens": before_tokens},
    ) as span:
        yield span


@contextmanager
def trace_intent_classify(source: str) -> Iterator[trace.Span]:
    """Span ``intent.classify``."""
    with _span(
        "intent.classify",
        {"service.name": "open-chat-shop", "source": source},
    ) as span:
        yield span


@contextmanager
def trace_tool_inject(intent: str) -> Iterator[trace.Span]:
    """Span ``tool.inject``."""
    with _span(
        "tool.inject",
        {"service.name": "open-chat-shop", "intent": intent},
    ) as span:
        yield span


@contextmanager
def trace_tool_execute(tool_name: str) -> Iterator[trace.Span]:
    """Span ``tool.execute``."""
    with _span(
        "tool.execute",
        {"service.name": "open-chat-shop", "tool_name": tool_name},
    ) as span:
        yield span


@contextmanager
def trace_security_check() -> Iterator[trace.Span]:
    """Span ``security.check``."""
    with _span(
        "security.check",
        {"service.name": "open-chat-shop"},
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
            "service.name": "open-chat-shop",
            "channel": channel,
            "original_type": original_type,
        },
    ) as span:
        yield span
