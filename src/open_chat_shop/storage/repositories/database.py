"""SQL-backed repository implementations using SQLModel / SQLAlchemy.

Each method converts SQLModel rows into plain dicts that match the shapes
expected by tool code (the same shapes defined in ``_mock_data.py``).
"""
from __future__ import annotations

import copy
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Engine, text
from sqlmodel import Session, select

from open_chat_shop.storage.models import (
    LogisticsRecord,
    Order,
    Product,
    RefundRecord,
)
from open_chat_shop.storage.repositories.abc import (
    LogisticsRepository,
    OrderRepository,
    ProductRepository,
    RefundRepository,
)


def _order_to_dict(row: Order) -> dict:
    """Convert a SQLModel Order row to the dict shape used by tools."""
    items = json.loads(row.items_json) if row.items_json else []
    addr_data = json.loads(row.address_json) if row.address_json else {}
    created_iso = row.created_at.isoformat() if row.created_at else ""
    # Ensure trailing Z for UTC datetimes that lack timezone info.
    if created_iso and not created_iso.endswith("Z"):
        created_iso += "Z"
    return {
        "order_id": row.id,
        "status": row.status,
        "items": items,
        "total_amount": row.total_amount,
        "created_at": created_iso,
        "address": addr_data.get("full", ""),
        "phone": addr_data.get("phone", ""),
    }


def _product_to_dict(row: Product) -> dict:
    """Convert a SQLModel Product row to the dict shape used by tools."""
    return {
        "id": row.id,
        "name": row.name,
        "price": row.price,
        "category": row.category,
        "image_url": row.image_url or "",
    }


def _logistics_to_dict(row: LogisticsRecord) -> dict:
    """Convert a SQLModel LogisticsRecord row to the dict shape used by tools."""
    timeline = json.loads(row.timeline_json) if row.timeline_json else []
    return {
        "order_id": row.order_id,
        "carrier": row.carrier,
        "tracking_number": row.tracking_number,
        "timeline": timeline,
    }


# ---------------------------------------------------------------------------
# DatabaseOrderRepository
# ---------------------------------------------------------------------------


class DatabaseOrderRepository(OrderRepository):
    """Order data backed by a SQLModel engine."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._snapshots: dict[str, dict] = {}

    def get(self, order_id: str) -> dict | None:
        with Session(self._engine) as session:
            row = session.get(Order, order_id)
            if row is None:
                return None
            return _order_to_dict(row)

    def update_status(self, order_id: str, status: str, **extras: str) -> dict | None:
        with Session(self._engine) as session:
            row = session.get(Order, order_id)
            if row is None:
                return None
            row.status = status
            for k, v in extras.items():
                if hasattr(row, k):
                    setattr(row, k, v)
            row.updated_at = datetime.now(timezone.utc)
            session.add(row)
            session.commit()
            session.refresh(row)
            return _order_to_dict(row)

    def update_address(
        self,
        order_id: str,
        address: str,
        phone: str | None = None,
    ) -> tuple[dict | None, str]:
        with Session(self._engine) as session:
            row = session.get(Order, order_id)
            if row is None:
                return None, ""
            old_data = json.loads(row.address_json) if row.address_json else {}
            old_address = old_data.get("full", "")
            new_data = {**old_data, "full": address}
            if phone is not None:
                new_data["phone"] = phone
            row.address_json = json.dumps(new_data, ensure_ascii=False)
            row.updated_at = datetime.now(timezone.utc)
            session.add(row)
            session.commit()
            session.refresh(row)
            return _order_to_dict(row), old_address

    def save_snapshot(self, order_id: str) -> None:
        order_dict = self.get(order_id)
        if order_dict is not None:
            self._snapshots[order_id] = copy.deepcopy(order_dict)

    def restore_snapshot(self, order_id: str) -> bool:
        snapshot = self._snapshots.pop(order_id, None)
        if snapshot is None:
            return False
        with Session(self._engine) as session:
            row = session.get(Order, order_id)
            if row is None:
                return False
            row.status = snapshot["status"]
            row.total_amount = snapshot["total_amount"]
            row.items_json = json.dumps(snapshot["items"], ensure_ascii=False)
            addr = {"full": snapshot.get("address", ""), "phone": snapshot.get("phone", "")}
            row.address_json = json.dumps(addr, ensure_ascii=False)
            row.updated_at = datetime.now(timezone.utc)
            session.add(row)
            session.commit()
        return True


# ---------------------------------------------------------------------------
# DatabaseProductRepository
# ---------------------------------------------------------------------------


class DatabaseProductRepository(ProductRepository):
    """Product data backed by a SQLModel engine."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def search(
        self,
        keyword: str,
        category: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        with Session(self._engine) as session:
            statement = select(Product).where(
                Product.name.ilike(f"%{keyword}%")
            )
            if category:
                statement = statement.where(Product.category == category)
            statement = statement.limit(limit)
            rows = session.exec(statement).all()
            return [_product_to_dict(r) for r in rows]

    def get(self, product_id: str) -> dict | None:
        with Session(self._engine) as session:
            row = session.get(Product, product_id)
            if row is None:
                return None
            return _product_to_dict(row)


# ---------------------------------------------------------------------------
# DatabaseLogisticsRepository
# ---------------------------------------------------------------------------


class DatabaseLogisticsRepository(LogisticsRepository):
    """Logistics data backed by a SQLModel engine."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def get_by_order(self, order_id: str) -> dict | None:
        with Session(self._engine) as session:
            statement = select(LogisticsRecord).where(
                LogisticsRecord.order_id == order_id
            )
            row = session.exec(statement).first()
            if row is None:
                return None
            return _logistics_to_dict(row)


# ---------------------------------------------------------------------------
# DatabaseRefundRepository
# ---------------------------------------------------------------------------


class DatabaseRefundRepository(RefundRepository):
    """Refund data backed by a SQLModel engine."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def create(self, order_id: str, amount: float, reason: str) -> dict:
        refund_id = f"REF-{uuid.uuid4().hex[:8].upper()}"
        now = datetime.now(timezone.utc)
        row = RefundRecord(
            id=refund_id,
            order_id=order_id,
            user_id="user-seed-default",
            reason=reason,
            amount=amount,
            status="processing",
            created_at=now,
            updated_at=now,
        )
        with Session(self._engine) as session:
            session.add(row)
            session.commit()
        return {
            "refund_id": refund_id,
            "order_id": order_id,
            "amount": amount,
            "reason": reason,
            "status": "processing",
        }

    def delete_processing_by_order(self, order_id: str) -> None:
        with Session(self._engine) as session:
            statement = select(RefundRecord).where(
                RefundRecord.order_id == order_id,
                RefundRecord.status == "processing",
            )
            rows = session.exec(statement).all()
            for row in rows:
                session.delete(row)
            session.commit()
