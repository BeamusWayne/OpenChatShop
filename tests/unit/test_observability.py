"""Tests for commerce_agent.observability.logging.

Covers:
- StructuredFormatter: valid JSON output, required fields, extra fields
- AuditLogger: tool execution and security event logging
- CostTracker: recording, cost calculation, summary aggregation, empty state
- _sanitize_params: sensitive key removal
- setup_logging: handler configuration
"""
from __future__ import annotations

import json
import logging

import pytest

from commerce_agent.observability.logging import (
    AuditLogger,
    CostTracker,
    StructuredFormatter,
    _sanitize_params,
    setup_logging,
)


# -- StructuredFormatter ------------------------------------------------------


@pytest.mark.unit
def test_structured_formatter_outputs_valid_json() -> None:
    """format() must return parseable JSON."""
    fmt = StructuredFormatter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg="hello",
        args=(),
        exc_info=None,
    )
    output = fmt.format(record)
    parsed = json.loads(output)
    assert isinstance(parsed, dict)


@pytest.mark.unit
def test_structured_formatter_includes_required_fields() -> None:
    """Every formatted line must contain timestamp, level, module, event."""
    fmt = StructuredFormatter()
    record = logging.LogRecord(
        name="test",
        level=logging.WARNING,
        pathname="test.py",
        lineno=1,
        msg="something happened",
        args=(),
        exc_info=None,
    )
    parsed = json.loads(fmt.format(record))

    assert "timestamp" in parsed
    assert parsed["level"] == "WARNING"
    assert parsed["module"] == "test"  # default module from LogRecord
    assert parsed["event"] == "something happened"


@pytest.mark.unit
def test_structured_formatter_handles_extra_fields() -> None:
    """Extra record attributes (trace_id, span_id, session_id) appear in output."""
    fmt = StructuredFormatter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg="msg",
        args=(),
        exc_info=None,
    )
    record.trace_id = "trace-123"  # type: ignore[attr-defined]
    record.span_id = "span-456"  # type: ignore[attr-defined]
    record.session_id = "sess-789"  # type: ignore[attr-defined]
    record.duration_ms = 42.5  # type: ignore[attr-defined]
    record.details = {"key": "value"}  # type: ignore[attr-defined]

    parsed = json.loads(fmt.format(record))
    assert parsed["trace_id"] == "trace-123"
    assert parsed["span_id"] == "span-456"
    assert parsed["session_id"] == "sess-789"
    assert parsed["duration_ms"] == 42.5
    assert parsed["details"] == {"key": "value"}


@pytest.mark.unit
def test_structured_formatter_omits_missing_optional_fields() -> None:
    """When no extra attributes are set, optional fields should be absent."""
    fmt = StructuredFormatter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg="plain",
        args=(),
        exc_info=None,
    )
    parsed = json.loads(fmt.format(record))
    for field in ("trace_id", "span_id", "session_id", "duration_ms", "details"):
        assert field not in parsed


@pytest.mark.unit
def test_structured_formatter_uses_module_name_override() -> None:
    """module_name extra attribute overrides the default module field."""
    fmt = StructuredFormatter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg="msg",
        args=(),
        exc_info=None,
    )
    record.module_name = "custom.module"  # type: ignore[attr-defined]
    parsed = json.loads(fmt.format(record))
    assert parsed["module"] == "custom.module"


# -- AuditLogger -------------------------------------------------------------


@pytest.mark.unit
def test_audit_logger_logs_tool_execution(capfd: pytest.CaptureFixture[str]) -> None:
    """log_tool_execution emits a structured log line via the audit logger."""
    # Configure a handler so output goes to stderr (StreamHandler default).
    handler = logging.StreamHandler()
    handler.setFormatter(StructuredFormatter())
    logger = logging.getLogger("commerce_agent.audit.tool_test")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.addHandler(handler)

    audit = AuditLogger(logger_name="tool_test")
    audit.log_tool_execution(
        tool_name="query_order",
        user_id="u-001",
        session_id="s-100",
        params={"order_id": "ORD-999"},
        result="success",
    )

    captured = capfd.readouterr()
    # StreamHandler writes to stderr by default
    output = captured.err or captured.out
    assert "query_order" in output or "tool.execute.success" in output


@pytest.mark.unit
def test_audit_logger_logs_security_event(capfd: pytest.CaptureFixture[str]) -> None:
    """log_security_event emits a WARNING level structured log."""
    handler = logging.StreamHandler()
    handler.setFormatter(StructuredFormatter())
    logger = logging.getLogger("commerce_agent.audit.sec_test")
    logger.setLevel(logging.WARNING)
    logger.handlers.clear()
    logger.addHandler(handler)

    audit = AuditLogger(logger_name="sec_test")
    audit.log_security_event(
        event="injection.attempt.detected",
        session_id="s-200",
        details={"pattern": "ignore_previous"},
    )

    captured = capfd.readouterr()
    output = captured.err or captured.out
    assert "injection.attempt.detected" in output


# -- CostTracker -------------------------------------------------------------


@pytest.mark.unit
def test_cost_tracker_records_usage() -> None:
    """record() stores an entry and returns the calculated cost."""
    tracker = CostTracker()
    cost = tracker.record("gpt-4o-mini", prompt_tokens=1000, completion_tokens=500)

    assert len(tracker._usage) == 1
    assert tracker._usage[0]["model"] == "gpt-4o-mini"
    assert tracker._usage[0]["prompt_tokens"] == 1000
    assert tracker._usage[0]["completion_tokens"] == 500
    assert cost > 0


@pytest.mark.unit
def test_cost_tracker_calculates_cost_correctly() -> None:
    """Cost is calculated using the per-model rate table."""
    tracker = CostTracker()

    # gpt-4o-mini: input $0.00015/1K, output $0.0006/1K
    # 2000 prompt * 0.00015/1000 = 0.0003
    # 1000 completion * 0.0006/1000 = 0.0006
    # total = 0.0009
    cost = tracker.record("gpt-4o-mini", prompt_tokens=2000, completion_tokens=1000)
    assert abs(cost - 0.0009) < 1e-9


@pytest.mark.unit
def test_cost_tracker_uses_default_for_unknown_model() -> None:
    """Unknown models fall back to DEFAULT_COST rates."""
    tracker = CostTracker()
    cost = tracker.record("unknown-model", prompt_tokens=1000, completion_tokens=1000)
    # default: input $0.001/1K, output $0.003/1K
    # 1000 * 0.001/1000 + 1000 * 0.003/1000 = 0.001 + 0.003 = 0.004
    assert abs(cost - 0.004) < 1e-9


@pytest.mark.unit
def test_cost_tracker_summary_aggregates_by_model() -> None:
    """get_summary() returns totals and per-model breakdowns."""
    tracker = CostTracker()
    tracker.record("gpt-4o-mini", 1000, 500)
    tracker.record("gpt-4o", 2000, 1000)
    tracker.record("gpt-4o-mini", 500, 250)

    summary = tracker.get_summary()
    assert summary["total_requests"] == 3
    assert summary["total_tokens"] == 1000 + 500 + 2000 + 1000 + 500 + 250
    assert summary["total_cost_usd"] > 0
    assert "gpt-4o-mini" in summary["by_model"]
    assert "gpt-4o" in summary["by_model"]
    assert summary["by_model"]["gpt-4o-mini"]["requests"] == 2
    assert summary["by_model"]["gpt-4o"]["requests"] == 1


@pytest.mark.unit
def test_cost_tracker_summary_empty_when_no_usage() -> None:
    """get_summary() returns zeroes when nothing has been recorded."""
    tracker = CostTracker()
    summary = tracker.get_summary()
    assert summary == {"total_requests": 0, "total_tokens": 0, "total_cost_usd": 0.0}


# -- _sanitize_params --------------------------------------------------------


@pytest.mark.unit
def test_sanitize_params_removes_sensitive_keys() -> None:
    """Sensitive keys are replaced with '***', others are preserved."""
    params = {
        "order_id": "ORD-123",
        "password": "hunter2",
        "api_key": "sk-abc123",
        "credit_card": "4111111111111111",
        "cvv": "999",
        "token": "bearer-xyz",
        "secret": "my-secret",
        "normal_field": "visible",
    }
    result = _sanitize_params(params)
    assert result["order_id"] == "ORD-123"
    assert result["password"] == "***"
    assert result["api_key"] == "***"
    assert result["credit_card"] == "***"
    assert result["cvv"] == "***"
    assert result["token"] == "***"
    assert result["secret"] == "***"
    assert result["normal_field"] == "visible"


# -- setup_logging -----------------------------------------------------------


@pytest.mark.unit
def test_setup_logging_configures_handler() -> None:
    """setup_logging attaches a StructuredFormatter handler to the commerce_agent logger."""
    setup_logging(level="DEBUG")
    root = logging.getLogger("commerce_agent")
    assert root.level == logging.DEBUG
    assert len(root.handlers) == 1
    handler = root.handlers[0]
    assert isinstance(handler.formatter, StructuredFormatter)
