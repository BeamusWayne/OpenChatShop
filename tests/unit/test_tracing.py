"""Tests for open_chat_shop.observability.tracing.

Uses InMemorySpanExporter to verify span creation, naming, attributes,
duration recording, and exception handling without a real OTLP collector.
"""
from __future__ import annotations

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from open_chat_shop.observability.tracing import (
    _console_enabled,
    get_tracer,
    setup_tracing,
    trace_channel_adapt,
    trace_context_compress,
    trace_context_load,
    trace_intent_classify,
    trace_orchestrator_handle,
    trace_provider_cascade,
    trace_provider_chat,
    trace_security_check,
    trace_tool_execute,
    trace_tool_inject,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_global_tracer() -> None:
    """Reset the module-level tracer between tests."""
    import open_chat_shop.observability.tracing as mod

    mod._tracer = None
    yield
    mod._tracer = None


@pytest.fixture()
def memory_exporter() -> InMemorySpanExporter:
    """Create an InMemorySpanExporter wired into the global tracer."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    import open_chat_shop.observability.tracing as mod

    mod._tracer = provider.get_tracer("test")
    return exporter


# ---------------------------------------------------------------------------
# setup_tracing
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_setup_tracing_creates_tracer() -> None:
    """setup_tracing returns a usable Tracer."""
    tracer = setup_tracing(service_name="test-svc")
    assert tracer is not None
    # The returned tracer should be the same one get_tracer() returns.
    assert get_tracer() is tracer


@pytest.mark.unit
def test_get_tracer_lazy_init() -> None:
    """get_tracer creates a default tracer when none has been set up."""
    tracer = get_tracer()
    assert tracer is not None


# ---------------------------------------------------------------------------
# Exporter defaults — quiet by default, console opt-in (audit P2)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExporterDefaults:
    """Default tracing must not spam stdout; console export is opt-in.

    Previously setup_tracing() with no endpoint installed a
    ConsoleSpanExporter, so every span was serialised to stdout — noisy and
    slow across a 500-sample evaluation run.
    """

    def test_default_setup_writes_no_span_to_stdout(self, capsys) -> None:
        """Core fix: a default tracer must not dump spans to stdout."""
        setup_tracing(service_name="quiet")
        with trace_orchestrator_handle("s1"):
            pass
        out = capsys.readouterr().out
        assert "orchestrator.handle_message" not in out

    # The console decision is a pure function (OTel's set-once provider makes
    # runtime stdout switching unreliable across the suite, so we test the
    # decision directly rather than the export side effect).
    def test_console_disabled_by_default(self, monkeypatch) -> None:
        monkeypatch.delenv("OTEL_CONSOLE_EXPORT", raising=False)
        assert _console_enabled(None) is False

    def test_console_explicit_arg_wins(self) -> None:
        assert _console_enabled(True) is True
        assert _console_enabled(False) is False

    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes"])
    def test_console_enabled_via_env(self, monkeypatch, value: str) -> None:
        monkeypatch.setenv("OTEL_CONSOLE_EXPORT", value)
        assert _console_enabled(None) is True

    def test_console_env_falsey_stays_off(self, monkeypatch) -> None:
        monkeypatch.setenv("OTEL_CONSOLE_EXPORT", "0")
        assert _console_enabled(None) is False


# ---------------------------------------------------------------------------
# trace_orchestrator_handle
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_trace_orchestrator_handle(memory_exporter: InMemorySpanExporter) -> None:
    """orchestrator.handle_message span has correct name and session_id."""
    with trace_orchestrator_handle("sess-001"):
        pass

    spans = memory_exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "orchestrator.handle_message"
    assert spans[0].attributes["session_id"] == "sess-001"
    assert spans[0].attributes["service.name"] == "open-chat-shop"


# ---------------------------------------------------------------------------
# trace_provider_chat
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_trace_provider_chat(memory_exporter: InMemorySpanExporter) -> None:
    """provider.chat span records the model attribute."""
    with trace_provider_chat("gpt-4o"):
        pass

    spans = memory_exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "provider.chat"
    assert spans[0].attributes["model"] == "gpt-4o"


# ---------------------------------------------------------------------------
# trace_provider_cascade
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_trace_provider_cascade(memory_exporter: InMemorySpanExporter) -> None:
    """provider.cascade span records models list and count."""
    with trace_provider_cascade(["gpt-4o", "claude-sonnet", "gpt-4o-mini"]):
        pass

    spans = memory_exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "provider.cascade"
    assert spans[0].attributes["models"] == "gpt-4o,claude-sonnet,gpt-4o-mini"
    assert spans[0].attributes["model_count"] == 3


# ---------------------------------------------------------------------------
# trace_context_load
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_trace_context_load(memory_exporter: InMemorySpanExporter) -> None:
    """context.load span records session_id."""
    with trace_context_load("sess-42"):
        pass

    spans = memory_exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "context.load"
    assert spans[0].attributes["session_id"] == "sess-42"


# ---------------------------------------------------------------------------
# trace_context_compress
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_trace_context_compress(memory_exporter: InMemorySpanExporter) -> None:
    """context.compress span records before_tokens and allows after_tokens."""
    with trace_context_compress(before_tokens=8000) as span:
        span.set_attribute("after_tokens", 2000)

    spans = memory_exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "context.compress"
    assert spans[0].attributes["before_tokens"] == 8000
    assert spans[0].attributes["after_tokens"] == 2000


# ---------------------------------------------------------------------------
# trace_intent_classify
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_trace_intent_classify(memory_exporter: InMemorySpanExporter) -> None:
    """intent.classify span records source and allows intent attribute."""
    with trace_intent_classify(source="rule_engine") as span:
        span.set_attribute("intent", "query_order")
        span.set_attribute("confidence", 0.95)

    spans = memory_exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "intent.classify"
    assert spans[0].attributes["source"] == "rule_engine"
    assert spans[0].attributes["intent"] == "query_order"


# ---------------------------------------------------------------------------
# trace_tool_inject
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_trace_tool_inject(memory_exporter: InMemorySpanExporter) -> None:
    """tool.inject span records intent and allows tool count."""
    with trace_tool_inject(intent="query_order") as span:
        span.set_attribute("tool_count", 3)

    spans = memory_exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "tool.inject"
    assert spans[0].attributes["intent"] == "query_order"
    assert spans[0].attributes["tool_count"] == 3


# ---------------------------------------------------------------------------
# trace_tool_execute
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_trace_tool_execute(memory_exporter: InMemorySpanExporter) -> None:
    """tool.execute span records tool_name and allows success attribute."""
    with trace_tool_execute("query_order") as span:
        span.set_attribute("success", True)

    spans = memory_exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "tool.execute"
    assert spans[0].attributes["tool_name"] == "query_order"
    assert spans[0].attributes["success"] is True


# ---------------------------------------------------------------------------
# trace_security_check
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_trace_security_check_passed(memory_exporter: InMemorySpanExporter) -> None:
    """security.check span records passed result."""
    with trace_security_check() as span:
        span.set_attribute("result", "passed")

    spans = memory_exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "security.check"
    assert spans[0].attributes["result"] == "passed"


@pytest.mark.unit
def test_trace_security_check_blocked(memory_exporter: InMemorySpanExporter) -> None:
    """security.check span records blocked result."""
    with trace_security_check() as span:
        span.set_attribute("result", "blocked")

    spans = memory_exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].attributes["result"] == "blocked"


# ---------------------------------------------------------------------------
# trace_channel_adapt
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_trace_channel_adapt(memory_exporter: InMemorySpanExporter) -> None:
    """channel.adapt span records channel, original_type, and was_downgraded."""
    with trace_channel_adapt("wechat", "product_list") as span:
        span.set_attribute("was_downgraded", True)

    spans = memory_exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "channel.adapt"
    assert spans[0].attributes["channel"] == "wechat"
    assert spans[0].attributes["original_type"] == "product_list"
    assert spans[0].attributes["was_downgraded"] is True


# ---------------------------------------------------------------------------
# Exception recording
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_exception_is_recorded(memory_exporter: InMemorySpanExporter) -> None:
    """Exceptions raised inside a span are recorded and re-raised."""
    with pytest.raises(ValueError, match="boom"), trace_provider_chat("test-model"):
        raise ValueError("boom")

    spans = memory_exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].status.status_code == trace.StatusCode.ERROR
    # At least one exception event should have been recorded.
    events = spans[0].events
    assert len(events) >= 1
    assert "exception" in events[0].name.lower()


# ---------------------------------------------------------------------------
# duration_ms
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_duration_ms_is_set(memory_exporter: InMemorySpanExporter) -> None:
    """Every completed span has a duration_ms attribute >= 0."""
    with trace_orchestrator_handle("sess-dur"):
        pass

    spans = memory_exporter.get_finished_spans()
    assert len(spans) == 1
    assert "duration_ms" in spans[0].attributes
    assert spans[0].attributes["duration_ms"] >= 0
