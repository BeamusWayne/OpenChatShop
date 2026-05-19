"""Structured logging, audit logging, and cost tracking.

Implements contracts.md §14:
- §14.1: StructuredFormatter with standard log fields
- §14.2: CostTracker for token consumption monitoring
- §14.3: AuditLogger for write operations and sensitive actions
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any


class StructuredFormatter(logging.Formatter):
    """JSON structured log formatter.

    Outputs one JSON object per log line with the fields defined in
    contracts.md §14.1.  Extra attributes on the LogRecord (trace_id,
    span_id, session_id, module_name, duration_ms, details) are
    promoted to top-level keys when present.
    """

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "module": getattr(record, "module_name", record.module),
            "event": record.getMessage(),
        }

        # Optional fields — only included when the caller provides them.
        for attr in ("trace_id", "span_id", "session_id", "duration_ms", "details"):
            value = getattr(record, attr, None)
            if value is not None:
                log_entry[attr] = value

        return json.dumps(
            {k: v for k, v in log_entry.items() if v is not None},
            ensure_ascii=False,
        )


class AuditLogger:
    """Audit logger for write operations and sensitive actions (contracts.md §14.3)."""

    def __init__(self, logger_name: str = "audit") -> None:
        self._logger = logging.getLogger(f"open_chat_shop.audit.{logger_name}")

    def log_tool_execution(
        self,
        tool_name: str,
        user_id: str | None,
        session_id: str,
        params: dict,
        result: str,  # "success" | "failure"
    ) -> None:
        self._logger.info(
            f"tool.execute.{result}",
            extra={
                "audit": True,
                "tool_name": tool_name,
                "user_id": user_id,
                "session_id": session_id,
                "params": _sanitize_params(params),
                "result": result,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    def log_security_event(
        self,
        event: str,
        session_id: str | None,
        details: dict,
    ) -> None:
        self._logger.warning(
            event,
            extra={"audit": True, "session_id": session_id, "details": details},
        )


class CostTracker:
    """Track token consumption and costs per model."""

    # Approximate cost per 1K tokens (USD)
    COST_TABLE: dict[str, dict[str, float]] = {
        "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
        "gpt-4o": {"input": 0.005, "output": 0.015},
        "claude-sonnet": {"input": 0.003, "output": 0.015},
    }
    DEFAULT_COST: dict[str, float] = {"input": 0.001, "output": 0.003}

    def __init__(self) -> None:
        self._usage: list[dict] = []

    def record(self, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        costs = self.COST_TABLE.get(model, self.DEFAULT_COST)
        cost = (prompt_tokens / 1000 * costs["input"]) + (
            completion_tokens / 1000 * costs["output"]
        )
        entry = {
            "model": model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "cost_usd": round(cost, 6),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._usage.append(entry)
        return cost

    def get_summary(self) -> dict:
        if not self._usage:
            return {"total_requests": 0, "total_tokens": 0, "total_cost_usd": 0.0}
        return {
            "total_requests": len(self._usage),
            "total_tokens": sum(
                u["prompt_tokens"] + u["completion_tokens"] for u in self._usage
            ),
            "total_cost_usd": round(sum(u["cost_usd"] for u in self._usage), 6),
            "by_model": {
                model: {
                    "requests": len(
                        [u for u in self._usage if u["model"] == model]
                    ),
                    "tokens": sum(
                        u["prompt_tokens"] + u["completion_tokens"]
                        for u in self._usage
                        if u["model"] == model
                    ),
                }
                for model in {u["model"] for u in self._usage}
            },
        }


def setup_logging(level: str = "INFO") -> None:
    """Configure structured logging for the application."""
    handler = logging.StreamHandler()
    handler.setFormatter(StructuredFormatter())

    root = logging.getLogger("open_chat_shop")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.handlers.clear()
    root.addHandler(handler)


def _sanitize_params(params: dict) -> dict:
    """Remove sensitive fields from params for audit logging."""
    sensitive_keys = {"password", "token", "secret", "api_key", "credit_card", "cvv"}
    return {
        k: "***" if k.lower() in sensitive_keys else v for k, v in params.items()
    }
