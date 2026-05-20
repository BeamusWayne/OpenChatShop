"""Seed the database with default mock data when tables are empty.

This ensures a fresh database is immediately usable with the same data
that the in-memory repositories expose via ``_mock_data.py``.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import Engine, text
from sqlmodel import Session

from open_chat_shop.storage.models import (
    LogisticsRecord,
    Order,
    Product,
    User,
)
from open_chat_shop.tools.builtin import _mock_data as _md


def seed_if_empty(engine: Engine) -> None:
    """Populate tables from ``_mock_data`` when the product table is empty."""
    with Session(engine) as session:
        count = session.exec(text("SELECT COUNT(*) FROM product")).scalar()
        if count and int(count) > 0:
            return

        # --- Default user ---
        session.add(User(
            id="user-seed-default",
            name="种子用户",
            level="normal",
        ))

        # --- Products ---
        for p in _md.PRODUCTS:
            session.add(Product(
                id=p["id"],
                name=p["name"],
                category=p.get("category", ""),
                price=p["price"],
                image_url=p.get("image_url", ""),
            ))

        # --- Orders ---
        for order_id, o in _md.ORDERS.items():
            created_str = o.get("created_at", "")
            created_at = _parse_iso(created_str)
            addr_json = json.dumps(
                {"full": o.get("address", ""), "phone": o.get("phone", "")},
                ensure_ascii=False,
            )
            session.add(Order(
                id=o["order_id"],
                user_id="user-seed-default",
                status=o["status"],
                total_amount=o["total_amount"],
                items_json=json.dumps(o["items"], ensure_ascii=False),
                address_json=addr_json,
                created_at=created_at,
                updated_at=created_at,
            ))

        # --- Logistics ---
        for order_id, lg in _md.LOGISTICS.items():
            session.add(LogisticsRecord(
                order_id=lg["order_id"],
                carrier=lg["carrier"],
                tracking_number=lg["tracking_number"],
                timeline_json=json.dumps(lg["timeline"], ensure_ascii=False),
            ))

        session.commit()


def _parse_iso(s: str) -> datetime:
    """Parse an ISO-8601 string (with or without trailing Z) to a UTC datetime."""
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return datetime.now(timezone.utc)
