"""Cost governance — session budgets, cost alerts, and budget-aware execution.

Integrates with CostTracker (observability) to enforce per-session token
budgets and trigger alerts when spending exceeds configured thresholds.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum

logger = logging.getLogger(__name__)


class AlertLevel(StrEnum):
    NONE = "none"
    WARNING = "warning"
    CRITICAL = "critical"
    EXCEEDED = "exceeded"


@dataclass
class BudgetConfig:
    """Token budget configuration for a single session."""
    max_tokens: int = 50_000
    warning_threshold: float = 0.8   # 80% of max
    critical_threshold: float = 0.95  # 95% of max
    hard_stop: bool = True           # Block LLM calls when exceeded


@dataclass
class BudgetStatus:
    """Current budget consumption status."""
    used_tokens: int = 0
    max_tokens: int = 50_000
    alert_level: AlertLevel = AlertLevel.NONE
    remaining_tokens: int = field(init=False)
    usage_percent: float = field(init=False)

    def __post_init__(self) -> None:
        self.remaining_tokens = max(0, self.max_tokens - self.used_tokens)
        self.usage_percent = round(self.used_tokens / self.max_tokens * 100, 1) if self.max_tokens > 0 else 0.0


@dataclass
class CostAlert:
    """An alert triggered by cost threshold crossing."""
    level: AlertLevel
    session_id: str
    used_tokens: int
    max_tokens: int
    message: str


class SessionBudgetManager:
    """Track and enforce per-session token budgets."""

    def __init__(self, config: BudgetConfig | None = None) -> None:
        self._config = config or BudgetConfig()
        self._sessions: dict[str, int] = {}  # session_id -> used_tokens

    def consume(self, session_id: str, tokens: int) -> BudgetStatus:
        """Record token consumption and return current status."""
        self._sessions[session_id] = self._sessions.get(session_id, 0) + tokens
        return self.get_status(session_id)

    def get_status(self, session_id: str) -> BudgetStatus:
        """Get current budget status for a session."""
        used = self._sessions.get(session_id, 0)
        pct = used / self._config.max_tokens if self._config.max_tokens > 0 else 0.0

        if pct >= 1.0:
            level = AlertLevel.EXCEEDED
        elif pct >= self._config.critical_threshold:
            level = AlertLevel.CRITICAL
        elif pct >= self._config.warning_threshold:
            level = AlertLevel.WARNING
        else:
            level = AlertLevel.NONE

        return BudgetStatus(
            used_tokens=used,
            max_tokens=self._config.max_tokens,
            alert_level=level,
        )

    def can_proceed(self, session_id: str) -> bool:
        """Check if LLM calls are allowed for this session."""
        if not self._config.hard_stop:
            return True
        status = self.get_status(session_id)
        return status.alert_level != AlertLevel.EXCEEDED

    def reset(self, session_id: str) -> None:
        """Reset budget for a session."""
        self._sessions.pop(session_id, None)

    def set_budget(self, session_id: str, tokens: int) -> None:
        """Override budget for a specific session."""
        self._sessions[session_id] = tokens


class CostAlertEngine:
    """Generate and manage cost alerts."""

    def __init__(self) -> None:
        self._alerts: list[CostAlert] = []

    def check_and_alert(
        self,
        session_id: str,
        status: BudgetStatus,
    ) -> CostAlert | None:
        """Check status and create alert if threshold crossed."""
        if status.alert_level == AlertLevel.NONE:
            return None

        alert = CostAlert(
            level=status.alert_level,
            session_id=session_id,
            used_tokens=status.used_tokens,
            max_tokens=status.max_tokens,
            message=self._build_message(session_id, status),
        )
        self._alerts.append(alert)
        logger.warning(
            "Cost alert: %s session=%s used=%d max=%d",
            status.alert_level.value,
            session_id,
            status.used_tokens,
            status.max_tokens,
        )
        return alert

    def get_alerts(self, session_id: str | None = None) -> list[CostAlert]:
        """Get alerts, optionally filtered by session."""
        if session_id is None:
            return list(self._alerts)
        return [a for a in self._alerts if a.session_id == session_id]

    def clear_alerts(self, session_id: str | None = None) -> int:
        """Clear alerts, return count cleared."""
        if session_id is None:
            count = len(self._alerts)
            self._alerts.clear()
            return count
        before = len(self._alerts)
        self._alerts = [a for a in self._alerts if a.session_id != session_id]
        return before - len(self._alerts)

    @staticmethod
    def _build_message(session_id: str, status: BudgetStatus) -> str:
        pct = status.usage_percent
        if status.alert_level == AlertLevel.EXCEEDED:
            return f"Session {session_id} has exceeded token budget ({pct}%)"
        elif status.alert_level == AlertLevel.CRITICAL:
            return f"Session {session_id} at critical usage ({pct}%)"
        else:
            return f"Session {session_id} approaching budget limit ({pct}%)"
