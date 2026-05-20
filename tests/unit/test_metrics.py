"""Tests for the Prometheus metrics module."""
from __future__ import annotations

import pytest


def _metrics_text() -> str:
    """Return the current metrics exposition as a decoded string."""
    from open_chat_shop.observability.metrics import get_metrics_content

    return get_metrics_content().decode("utf-8")


class TestRecordChatRequest:
    def test_counter_incremented(self) -> None:
        from open_chat_shop.observability.metrics import record_chat_request

        record_chat_request("order_query", "ok")
        text = _metrics_text()
        assert "openchatshop_chat_requests_total" in text


class TestRecordLlmCall:
    def test_counter_incremented(self) -> None:
        from open_chat_shop.observability.metrics import record_llm_call

        record_llm_call(
            model="glm-5.1",
            status="ok",
            prompt_tokens=100,
            completion_tokens=50,
            cost_usd=0.002,
        )
        text = _metrics_text()
        assert "openchatshop_llm_calls_total" in text
        assert "openchatshop_llm_tokens_total" in text
        assert "openchatshop_llm_cost_usd_total" in text


class TestRecordToolCall:
    def test_counter_incremented(self) -> None:
        from open_chat_shop.observability.metrics import record_tool_call

        record_tool_call("query_order", "ok")
        text = _metrics_text()
        assert "openchatshop_tool_calls_total" in text


class TestRecordCacheHit:
    def test_counter_incremented(self) -> None:
        from open_chat_shop.observability.metrics import record_cache_hit

        record_cache_hit("order_query")
        text = _metrics_text()
        assert "openchatshop_cache_hits_total" in text


class TestObserveChatDuration:
    def test_histogram_observed(self) -> None:
        from open_chat_shop.observability.metrics import observe_chat_duration

        observe_chat_duration("order_query", 0.45)
        text = _metrics_text()
        assert "openchatshop_chat_duration_seconds" in text


class TestGauges:
    def test_active_sessions_gauge_exists(self) -> None:
        text = _metrics_text()
        assert "openchatshop_active_sessions" in text

    def test_handoff_queue_size_gauge_exists(self) -> None:
        text = _metrics_text()
        assert "openchatshop_handoff_queue_size" in text


class TestGetMetricsContent:
    def test_returns_bytes(self) -> None:
        from open_chat_shop.observability.metrics import get_metrics_content

        result = get_metrics_content()
        assert isinstance(result, bytes)
        assert len(result) > 0
