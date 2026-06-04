"""Shared scaffold for order-mutation tools.

cancel_order, modify_address and create_refund all follow the same shape:

    1. load the order via ``get_for_user`` (ownership + existence guard)
    2. reject on a tool-specific status guard
    3. perform the mutation
    4. on failure, compensation restores the prior state

This module factors that scaffold into :class:`OrderMutationTool`, a
template-method base class. Each concrete tool supplies only the parts that
genuinely differ — the status guard and the mutation — while ownership
enforcement (IDOR/BOLA, audit CRITICAL-1), the not-found behaviour and the
``pre_check``/``execute`` symmetry stay defined in exactly one place.
"""

from __future__ import annotations

from typing import Any

from open_chat_shop.core.tool import BaseTool
from open_chat_shop.core.types import CheckResult, SessionContext, ToolResult
from open_chat_shop.storage.repositories.abc import OrderRepository
from open_chat_shop.storage.repositories.memory import InMemoryOrderRepository


class OrderMutationTool(BaseTool):
    """Template base for tools that mutate a single user-owned order.

    Subclasses implement two hooks:

    * :meth:`_status_reasons` — given an order, return the rejection reasons
      ``(zh, en)`` when its status forbids the mutation, else ``None``. The
      Chinese reason is surfaced to the user by ``pre_check``; the English one
      is returned by ``execute`` as defence in depth so a direct caller cannot
      bypass the guard. A tool may set the English entry to ``None`` to opt a
      stage out of the status guard (matching pre-existing behaviour).
    * :meth:`_perform` — carry out the mutation and return the success payload.

    The fetch uses :meth:`OrderRepository.get_for_user`, so a non-owned or
    missing order is uniformly reported as not-found — no enumeration oracle and
    no mutation of another user's order.
    """

    def __init__(self, order_repo: OrderRepository | None = None) -> None:
        self._order_repo = order_repo or InMemoryOrderRepository()

    # ------------------------------------------------------------------
    # Hooks subclasses override
    # ------------------------------------------------------------------

    def _status_reasons(
        self, order: dict[str, Any], order_id: str
    ) -> tuple[str | None, str | None] | None:
        """Return ``(zh_reason, en_reason)`` if the status blocks the mutation.

        Returning ``None`` means the status is acceptable. Within the tuple, a
        ``None`` entry skips the rejection for that stage (``zh`` -> pre_check,
        ``en`` -> execute). Default: no status restriction.
        """
        return None

    def _perform(
        self,
        order: dict[str, Any],
        order_id: str,
        params: dict[str, Any],
        context: SessionContext,
    ) -> dict[str, Any]:
        """Perform the mutation and return the ``ToolResult.data`` payload.

        Subclasses MUST implement. Implementations own any snapshotting needed
        for :meth:`compensate` to be able to roll back.
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Shared lifecycle — defined once
    # ------------------------------------------------------------------

    async def pre_check(self, params: dict[str, Any], context: SessionContext) -> CheckResult:
        order_id = params["order_id"]
        order = self._order_repo.get_for_user(order_id, context.user_id)
        if order is None:
            return CheckResult(passed=False, reason=f"订单 {order_id} 不存在")
        reasons = self._status_reasons(order, order_id)
        if reasons is not None and reasons[0] is not None:
            return CheckResult(passed=False, reason=reasons[0])
        return CheckResult(passed=True)

    async def execute(self, params: dict[str, Any], context: SessionContext) -> ToolResult:
        order_id = params["order_id"]

        order = self._order_repo.get_for_user(order_id, context.user_id)
        if order is None:
            return ToolResult(success=False, error=f"Order {order_id} not found")

        reasons = self._status_reasons(order, order_id)
        if reasons is not None and reasons[1] is not None:
            return ToolResult(success=False, error=reasons[1])

        data = self._perform(order, order_id, params, context)
        return ToolResult(success=True, data=data)
