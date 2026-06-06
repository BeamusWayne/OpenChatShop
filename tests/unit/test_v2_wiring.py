"""Tests for V2.0 deployment wiring in main.py (feat-055).

The Multi-Agent path is wired into build_orchestrator behind ENABLE_MULTI_AGENT,
so it is off by default (existing behaviour byte-identical) and opt-in per
deployment.
"""
from __future__ import annotations

import pytest

from open_chat_shop.core.triage_router import TriageRouter


@pytest.fixture()
def main_mod(monkeypatch):
    # DEV_MODE before import: `import main` runs create_main_app() at module
    # level, which exits without auth configured. Then isolate from live LLM.
    monkeypatch.setenv("DEV_MODE", "true")
    import main as _main
    monkeypatch.setattr(_main, "_build_provider", lambda: None)
    return _main


@pytest.mark.unit
def test_multi_agent_off_by_default(monkeypatch, main_mod) -> None:
    monkeypatch.delenv("ENABLE_MULTI_AGENT", raising=False)
    orch = main_mod.build_orchestrator()
    assert orch._triage_router is None


@pytest.mark.unit
def test_enable_multi_agent_injects_router(monkeypatch, main_mod) -> None:
    monkeypatch.setenv("ENABLE_MULTI_AGENT", "1")
    orch = main_mod.build_orchestrator()
    assert isinstance(orch._triage_router, TriageRouter)
    # The router routes into the three default specialists.
    assert orch._triage_router.registry.domains == ["logistics", "refund", "sales"]
