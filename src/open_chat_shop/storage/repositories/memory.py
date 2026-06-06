"""In-memory repository implementations backed by _mock_data.py dicts.

These are the zero-config defaults. They reference the module-level mutable
dicts directly so that existing test fixtures (which also mutate those dicts)
continue to work unchanged.
"""
from __future__ import annotations

import copy
from typing import Any

from open_chat_shop.storage.repositories.abc import (
    HandoffRepository,
    LogisticsRepository,
    OrderRepository,
    ProductRepository,
    RefundRepository,
)
from open_chat_shop.tools.builtin import _mock_data as _md


class InMemoryOrderRepository(OrderRepository):
    """Wraps _mock_data.ORDERS with snapshot support."""

    def __init__(self) -> None:
        self._snapshots: dict[str, dict[str, Any]] = {}

    def get(self, order_id: str) -> dict[str, Any] | None:
        order = _md.ORDERS.get(order_id)
        if order is None:
            return None
        return order

    def update_status(self, order_id: str, status: str, **extras: str) -> dict[str, Any] | None:
        order = _md.ORDERS.get(order_id)
        if order is None:
            return None
        order["status"] = status
        for k, v in extras.items():
            order[k] = v
        return order

    def update_address(
        self,
        order_id: str,
        address: str,
        phone: str | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        order = _md.ORDERS.get(order_id)
        if order is None:
            return None, ""
        old_address = order.get("address", "")
        order["address"] = address
        if phone is not None:
            order["phone"] = phone
        return order, old_address

    def save_snapshot(self, order_id: str) -> None:
        order = _md.ORDERS.get(order_id)
        if order is not None:
            self._snapshots[order_id] = copy.deepcopy(order)

    def restore_snapshot(self, order_id: str) -> bool:
        snapshot = self._snapshots.pop(order_id, None)
        if snapshot is not None and order_id in _md.ORDERS:
            _md.ORDERS[order_id] = snapshot
            return True
        return False


class InMemoryProductRepository(ProductRepository):
    """Wraps _mock_data.PRODUCTS list."""

    def search(
        self,
        keyword: str,
        category: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        kw = keyword.lower()
        results: list[dict[str, Any]] = []
        for product in _md.PRODUCTS:
            if kw not in product["name"].lower():
                continue
            if category and product["category"] != category:
                continue
            results.append({
                "id": product["id"],
                "name": product["name"],
                "price": product["price"],
                "image_url": product.get("image_url", ""),
            })
            if len(results) >= limit:
                break
        return results

    def get(self, product_id: str) -> dict[str, Any] | None:
        for product in _md.PRODUCTS:
            if product["id"] == product_id:
                return product
        return None


class InMemoryLogisticsRepository(LogisticsRepository):
    """Wraps _mock_data.LOGISTICS dict."""

    def get_by_order(self, order_id: str) -> dict[str, Any] | None:
        return _md.LOGISTICS.get(order_id)


class InMemoryRefundRepository(RefundRepository):
    """Wraps _mock_data.REFUNDS and REFUND_COUNTER."""

    def create(self, order_id: str, amount: float, reason: str) -> dict[str, Any]:
        _md.REFUND_COUNTER += 1
        refund_id = f"REF-{_md.REFUND_COUNTER:04d}"
        record: dict[str, Any] = {
            "refund_id": refund_id,
            "order_id": order_id,
            "amount": amount,
            "reason": reason,
            "status": "processing",
        }
        _md.REFUNDS[refund_id] = record
        return record

    def delete_processing_by_order(self, order_id: str) -> None:
        to_remove = [
            rid for rid, ref in _md.REFUNDS.items()
            if ref["order_id"] == order_id and ref["status"] == "processing"
        ]
        for rid in to_remove:
            del _md.REFUNDS[rid]


class InMemoryHandoffRepository(HandoffRepository):
    """Returns a copy of HANDOFF_RESPONSE."""

    def get_response(self) -> dict[str, Any]:
        return dict(_md.HANDOFF_RESPONSE)


def create_in_memory_repositories() -> dict[str, Any]:
    """Create and return all InMemory repository instances."""
    return {
        "order": InMemoryOrderRepository(),
        "product": InMemoryProductRepository(),
        "logistics": InMemoryLogisticsRepository(),
        "refund": InMemoryRefundRepository(),
        "handoff": InMemoryHandoffRepository(),
    }
