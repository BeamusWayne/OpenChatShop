
"""Regression tests for audit cluster REPO.

CRITICAL: DatabaseOrderRepository._order_to_dict() dropped the owner field, so
the IDOR/BOLA guard OrderRepository.get_for_user() silently no-opped on the SQL
backend (owner stayed None, the ownership comparison never ran). On the
production storage path (DATABASE_URL set) any authenticated user could read,
cancel, refund, or re-address ANY order by guessing its ID.

These tests run the real get_for_user() guard against a SQLite-backed
DatabaseOrderRepository seeded with two distinct owners and assert that a
non-owner is denied (returned as None). They FAIL before the fix (the dict had
no ``customer_id``/owner key) and PASS after mapping ``row.user_id`` ->
``customer_id`` in _order_to_dict.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from sqlmodel import Session, SQLModel, create_engine

from open_chat_shop.storage.models import Order, User
from open_chat_shop.storage.repositories.database import DatabaseOrderRepository

OWNER_ID = "user-owner"
ATTACKER_ID = "user-attacker"
ORDER_ID = "ORD-SECRET-1"


@pytest.fixture()
def seeded_repo() -> DatabaseOrderRepository:
    """In-memory SQLite engine with two users and one order owned by OWNER_ID."""
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    now = datetime(2026, 5, 1, tzinfo=UTC)
    with Session(engine) as session:
        session.add(User(id=OWNER_ID, name="Owner", level="normal"))
        session.add(User(id=ATTACKER_ID, name="Attacker", level="normal"))
        session.add(Order(
            id=ORDER_ID,
            user_id=OWNER_ID,
            status="shipped",
            total_amount=228.0,
            items_json=json.dumps([{"name": "secret", "quantity": 1, "price": 228.0}]),
            address_json=json.dumps({"full": "addr", "phone": "13800138000"}),
            created_at=now,
            updated_at=now,
        ))
        session.commit()
    return DatabaseOrderRepository(engine)


def test_order_dict_includes_customer_id(seeded_repo: DatabaseOrderRepository) -> None:
    """_order_to_dict must surface the owner under the key the guard checks."""
    order = seeded_repo.get(ORDER_ID)
    assert order is not None
    # The guard reads order["customer_id"]; the model stores it as user_id.
    assert order["customer_id"] == OWNER_ID


def test_owner_can_access_their_order(seeded_repo: DatabaseOrderRepository) -> None:
    """The legitimate owner still gets their order through the guard."""
    order = seeded_repo.get_for_user(ORDER_ID, OWNER_ID)
    assert order is not None
    assert order["order_id"] == ORDER_ID


def test_non_owner_is_denied(seeded_repo: DatabaseOrderRepository) -> None:
    """IDOR guard: a different authenticated user must be denied (None).

    This is the core regression assertion. Before the fix the dict carried no
    owner, so get_for_user returned the order to ANYONE — a cross-tenant data
    exposure + unauthorized-mutation hole on the SQL backend.
    """
    assert seeded_repo.get_for_user(ORDER_ID, ATTACKER_ID) is None


def test_missing_order_returns_none(seeded_repo: DatabaseOrderRepository) -> None:
    """A non-existent order is None regardless of identity (no enumeration leak)."""
    assert seeded_repo.get_for_user("ORD-DOES-NOT-EXIST", OWNER_ID) is None


def test_no_identity_still_returns_order(seeded_repo: DatabaseOrderRepository) -> None:
    """Auth-disabled mode (user_id is None) returns the order as-is."""
    order = seeded_repo.get_for_user(ORDER_ID, None)
    assert order is not None
    assert order["order_id"] == ORDER_ID
