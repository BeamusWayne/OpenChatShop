"""Regression guard for the ``confirmation_threshold`` gate (audit LOW).

The audit warned that ``create_refund`` could bypass its ">500 requires
confirmation" gate by *omitting* ``amount``: the tool defaults an absent
``amount`` to the order's full total (``_perform``: ``refund_amount =
order["total_amount"]``), which may well exceed 500. If the gate read an
absent field as "below threshold", an unbounded refund would execute with no
confirmation.

The gate (``RuleBasedStrategy._needs_confirmation``) must therefore treat an
absent threshold field safe-side: the *true* value is unknown, so an
irreversible write still requires confirmation. These tests pin that contract
against the real ``CreateRefundTool`` permissions so a future change to either
the gate or the tool's defaulting can't silently re-open the bypass.
"""
from __future__ import annotations

from open_chat_shop.core.strategy import RuleBasedStrategy
from open_chat_shop.tools.builtin.create_refund import CreateRefundTool

_PERMS = CreateRefundTool.permissions


class TestConfirmationThresholdGate:
    def test_omitted_amount_still_requires_confirmation(self) -> None:
        # amount absent -> _perform defaults to the order total (may be >500).
        # Unknown value on an irreversible write => must confirm, not execute.
        params = {"order_id": "ORD-1", "reason": "不想要了"}
        assert RuleBasedStrategy._needs_confirmation(_PERMS, params) is True

    def test_amount_over_threshold_requires_confirmation(self) -> None:
        params = {"order_id": "ORD-1", "reason": "x", "amount": 600}
        assert RuleBasedStrategy._needs_confirmation(_PERMS, params) is True

    def test_amount_at_threshold_does_not_confirm(self) -> None:
        # gt:500 is strict — exactly 500 is not "over".
        params = {"order_id": "ORD-1", "reason": "x", "amount": 500}
        assert RuleBasedStrategy._needs_confirmation(_PERMS, params) is False

    def test_amount_under_threshold_does_not_confirm(self) -> None:
        params = {"order_id": "ORD-1", "reason": "x", "amount": 100}
        assert RuleBasedStrategy._needs_confirmation(_PERMS, params) is False

    def test_non_numeric_amount_is_gated_safe_side(self) -> None:
        # A malformed value can't be compared to the bound -> confirm.
        params = {"order_id": "ORD-1", "reason": "x", "amount": "lots"}
        assert RuleBasedStrategy._needs_confirmation(_PERMS, params) is True
