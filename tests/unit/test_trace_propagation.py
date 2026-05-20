"""Tests for trace_id / span_id propagation in orchestrator logs."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from open_chat_shop.core.orchestrator import DialogueOrchestrator


@pytest.fixture
def orchestrator() -> DialogueOrchestrator:
    """Return a DialogueOrchestrator with stubbed dependencies."""
    return DialogueOrchestrator(
        security_guard=MagicMock(),
        context_manager=MagicMock(),
        intent_engine=MagicMock(),
        tool_injector=MagicMock(),
        strategy=MagicMock(),
    )


class TestTraceExtras:
    def test_method_exists(self, orchestrator: DialogueOrchestrator) -> None:
        assert hasattr(orchestrator, "_trace_extras")

    def test_returns_dict(self, orchestrator: DialogueOrchestrator) -> None:
        result = orchestrator._trace_extras()
        assert isinstance(result, dict)

    def test_includes_session_id_when_provided(
        self, orchestrator: DialogueOrchestrator,
    ) -> None:
        result = orchestrator._trace_extras(session_id="sess-123")
        assert result.get("session_id") == "sess-123"

    def test_empty_without_session_id(
        self, orchestrator: DialogueOrchestrator,
    ) -> None:
        result = orchestrator._trace_extras()
        # Without an active span and without session_id, result is empty
        assert "session_id" not in result
