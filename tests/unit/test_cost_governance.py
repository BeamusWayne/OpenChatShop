"""Tests for cost governance — SessionBudgetManager and CostAlertEngine."""
from __future__ import annotations

import pytest

from open_chat_shop.core.cost_governance import (
    AlertLevel,
    BudgetConfig,
    BudgetStatus,
    CostAlertEngine,
    SessionBudgetManager,
)


class TestBudgetConfig:
    @pytest.mark.unit
    def test_defaults(self):
        cfg = BudgetConfig()
        assert cfg.max_tokens == 50_000
        assert cfg.warning_threshold == 0.8
        assert cfg.critical_threshold == 0.95
        assert cfg.hard_stop is True

    @pytest.mark.unit
    def test_custom_config(self):
        cfg = BudgetConfig(max_tokens=100_000, warning_threshold=0.7, hard_stop=False)
        assert cfg.max_tokens == 100_000
        assert cfg.hard_stop is False


class TestBudgetStatus:
    @pytest.mark.unit
    def test_remaining_tokens(self):
        status = BudgetStatus(used_tokens=20_000, max_tokens=50_000)
        assert status.remaining_tokens == 30_000

    @pytest.mark.unit
    def test_usage_percent(self):
        status = BudgetStatus(used_tokens=25_000, max_tokens=50_000)
        assert status.usage_percent == 50.0

    @pytest.mark.unit
    def test_zero_max_tokens(self):
        status = BudgetStatus(used_tokens=0, max_tokens=0)
        assert status.usage_percent == 0.0

    @pytest.mark.unit
    def test_over_budget_clamps_remaining(self):
        status = BudgetStatus(used_tokens=60_000, max_tokens=50_000)
        assert status.remaining_tokens == 0


class TestSessionBudgetManager:
    @pytest.mark.unit
    def test_initial_status_is_zero(self):
        mgr = SessionBudgetManager()
        status = mgr.get_status("s1")
        assert status.used_tokens == 0
        assert status.alert_level == AlertLevel.NONE

    @pytest.mark.unit
    def test_consume_tracks_tokens(self):
        mgr = SessionBudgetManager()
        status = mgr.consume("s1", 10_000)
        assert status.used_tokens == 10_000
        assert status.remaining_tokens == 40_000

    @pytest.mark.unit
    def test_multiple_consumes_accumulate(self):
        mgr = SessionBudgetManager()
        mgr.consume("s1", 20_000)
        status = mgr.consume("s1", 20_000)
        assert status.used_tokens == 40_000
        assert status.alert_level == AlertLevel.WARNING

    @pytest.mark.unit
    def test_warning_threshold(self):
        mgr = SessionBudgetManager(BudgetConfig(max_tokens=10_000, warning_threshold=0.8))
        status = mgr.consume("s1", 8_000)
        assert status.alert_level == AlertLevel.WARNING

    @pytest.mark.unit
    def test_critical_threshold(self):
        mgr = SessionBudgetManager(BudgetConfig(max_tokens=10_000, critical_threshold=0.95))
        status = mgr.consume("s1", 9_500)
        assert status.alert_level == AlertLevel.CRITICAL

    @pytest.mark.unit
    def test_exceeded(self):
        mgr = SessionBudgetManager(BudgetConfig(max_tokens=10_000))
        status = mgr.consume("s1", 10_000)
        assert status.alert_level == AlertLevel.EXCEEDED

    @pytest.mark.unit
    def test_can_proceed_under_budget(self):
        mgr = SessionBudgetManager()
        assert mgr.can_proceed("s1") is True

    @pytest.mark.unit
    def test_can_proceed_blocks_when_exceeded(self):
        mgr = SessionBudgetManager(BudgetConfig(max_tokens=1_000))
        mgr.consume("s1", 1_000)
        assert mgr.can_proceed("s1") is False

    @pytest.mark.unit
    def test_can_proceed_allows_when_no_hard_stop(self):
        mgr = SessionBudgetManager(BudgetConfig(max_tokens=1_000, hard_stop=False))
        mgr.consume("s1", 1_000)
        assert mgr.can_proceed("s1") is True

    @pytest.mark.unit
    def test_sessions_independent(self):
        mgr = SessionBudgetManager(BudgetConfig(max_tokens=1_000))
        mgr.consume("s1", 1_000)
        assert mgr.can_proceed("s1") is False
        assert mgr.can_proceed("s2") is True

    @pytest.mark.unit
    def test_reset_clears_session(self):
        mgr = SessionBudgetManager(BudgetConfig(max_tokens=1_000))
        mgr.consume("s1", 1_000)
        mgr.reset("s1")
        assert mgr.get_status("s1").used_tokens == 0
        assert mgr.can_proceed("s1") is True

    @pytest.mark.unit
    def test_set_budget_override(self):
        mgr = SessionBudgetManager(BudgetConfig(max_tokens=10_000))
        mgr.set_budget("s1", 9_500)
        status = mgr.get_status("s1")
        assert status.alert_level == AlertLevel.CRITICAL


class TestCostAlertEngine:
    @pytest.mark.unit
    def test_no_alert_when_ok(self):
        engine = CostAlertEngine()
        status = BudgetStatus(used_tokens=100, max_tokens=50_000, alert_level=AlertLevel.NONE)
        result = engine.check_and_alert("s1", status)
        assert result is None

    @pytest.mark.unit
    def test_warning_alert(self):
        engine = CostAlertEngine()
        status = BudgetStatus(used_tokens=42_000, max_tokens=50_000, alert_level=AlertLevel.WARNING)
        alert = engine.check_and_alert("s1", status)
        assert alert is not None
        assert alert.level == AlertLevel.WARNING
        assert alert.session_id == "s1"
        assert "approaching" in alert.message.lower() or "warning" in alert.level.value

    @pytest.mark.unit
    def test_critical_alert(self):
        engine = CostAlertEngine()
        status = BudgetStatus(
            used_tokens=48_000, max_tokens=50_000, alert_level=AlertLevel.CRITICAL
        )
        alert = engine.check_and_alert("s1", status)
        assert alert is not None
        assert alert.level == AlertLevel.CRITICAL
        assert "critical" in alert.message.lower()

    @pytest.mark.unit
    def test_exceeded_alert(self):
        engine = CostAlertEngine()
        status = BudgetStatus(
            used_tokens=55_000, max_tokens=50_000, alert_level=AlertLevel.EXCEEDED
        )
        alert = engine.check_and_alert("s1", status)
        assert alert is not None
        assert alert.level == AlertLevel.EXCEEDED

    @pytest.mark.unit
    def test_get_all_alerts(self):
        engine = CostAlertEngine()
        s1_status = BudgetStatus(
            used_tokens=42_000, max_tokens=50_000, alert_level=AlertLevel.WARNING
        )
        s2_status = BudgetStatus(
            used_tokens=50_000, max_tokens=50_000, alert_level=AlertLevel.EXCEEDED
        )
        engine.check_and_alert("s1", s1_status)
        engine.check_and_alert("s2", s2_status)
        assert len(engine.get_alerts()) == 2

    @pytest.mark.unit
    def test_get_alerts_by_session(self):
        engine = CostAlertEngine()
        s1_status = BudgetStatus(
            used_tokens=42_000, max_tokens=50_000, alert_level=AlertLevel.WARNING
        )
        s2_status = BudgetStatus(
            used_tokens=50_000, max_tokens=50_000, alert_level=AlertLevel.EXCEEDED
        )
        engine.check_and_alert("s1", s1_status)
        engine.check_and_alert("s2", s2_status)
        assert len(engine.get_alerts("s1")) == 1
        assert engine.get_alerts("s1")[0].level == AlertLevel.WARNING

    @pytest.mark.unit
    def test_clear_all_alerts(self):
        engine = CostAlertEngine()
        status = BudgetStatus(used_tokens=42_000, max_tokens=50_000, alert_level=AlertLevel.WARNING)
        engine.check_and_alert("s1", status)
        count = engine.clear_alerts()
        assert count == 1
        assert len(engine.get_alerts()) == 0

    @pytest.mark.unit
    def test_clear_session_alerts(self):
        engine = CostAlertEngine()
        s1_status = BudgetStatus(
            used_tokens=42_000, max_tokens=50_000, alert_level=AlertLevel.WARNING
        )
        s2_status = BudgetStatus(
            used_tokens=50_000, max_tokens=50_000, alert_level=AlertLevel.EXCEEDED
        )
        engine.check_and_alert("s1", s1_status)
        engine.check_and_alert("s2", s2_status)
        count = engine.clear_alerts("s1")
        assert count == 1
        assert len(engine.get_alerts()) == 1
        assert engine.get_alerts()[0].session_id == "s2"
