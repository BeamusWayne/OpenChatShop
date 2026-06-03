"""Repository ABCs — contracts for data access layers.

Return types are plain dicts matching the shapes in _mock_data.py so that
tool code and ToolResult payloads remain unchanged regardless of backend.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class OrderRepository(ABC):
    """Access and mutate order records."""

    @abstractmethod
    def get(self, order_id: str) -> dict | None:
        """Return order dict or None if not found."""

    @abstractmethod
    def update_status(self, order_id: str, status: str, **extras: str) -> dict | None:
        """Set order status (and optional extra fields). Returns updated order or None."""

    @abstractmethod
    def update_address(
        self,
        order_id: str,
        address: str,
        phone: str | None = None,
    ) -> tuple[dict | None, str]:
        """Update address (and optionally phone). Returns (updated_order, old_address)."""

    @abstractmethod
    def save_snapshot(self, order_id: str) -> None:
        """Deep-copy current order state for later restore."""

    @abstractmethod
    def restore_snapshot(self, order_id: str) -> bool:
        """Restore previously saved snapshot. Returns True if restored."""

    def get_for_user(self, order_id: str, user_id: str | None) -> dict | None:
        """Return the order only if it belongs to *user_id* (ownership check).

        This is the access point tools must use instead of :meth:`get`, to
        prevent IDOR/BOLA: an authenticated user must not read or mutate
        another user's order by guessing its ID.

        Ownership is enforced only when a caller identity is known (*user_id*
        is not None) and the order records an owner (``customer_id``). When no
        identity is established — e.g. auth disabled in local/dev mode — the
        order is returned as-is. A non-owned order is reported as None,
        indistinguishable from a missing one, to prevent order-ID enumeration.
        """
        order = self.get(order_id)
        if order is None:
            return None
        owner = order.get("customer_id")
        if user_id is not None and owner is not None and owner != user_id:
            return None
        return order


class ProductRepository(ABC):
    """Access product catalogue."""

    @abstractmethod
    def search(
        self,
        keyword: str,
        category: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        """Search products by keyword and optional category."""

    @abstractmethod
    def get(self, product_id: str) -> dict | None:
        """Return single product dict or None."""


class LogisticsRepository(ABC):
    """Access logistics / shipping records."""

    @abstractmethod
    def get_by_order(self, order_id: str) -> dict | None:
        """Return logistics dict for the given order, or None."""


class RefundRepository(ABC):
    """Create and manage refund records."""

    @abstractmethod
    def create(
        self,
        order_id: str,
        amount: float,
        reason: str,
    ) -> dict:
        """Create a new refund record. Returns the created refund dict."""

    @abstractmethod
    def delete_processing_by_order(self, order_id: str) -> None:
        """Remove all processing-status refunds for the given order."""


class HandoffRepository(ABC):
    """Static handoff configuration (read-only)."""

    @abstractmethod
    def get_response(self) -> dict:
        """Return the handoff response template dict."""
