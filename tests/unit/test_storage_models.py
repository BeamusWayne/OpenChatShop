"""Unit tests for SQLModel storage models and database utilities.

Verifies:
- All six table models: User, Product, Order, RefundRecord,
  ConversationLog, AuditRecord
- CRUD operations on each model
- Order status transitions
- RefundRecord status flow
- ConversationLog query by session_id
- AuditRecord risk_level filtering
- Relationships via foreign keys (User -> Orders, Order -> Refunds)
- Field constraint: Product.price >= 0
- Database utility functions: get_engine, create_tables, get_session, init_db
"""

from __future__ import annotations

import json
from datetime import datetime

import pytest
from sqlmodel import select

from commerce_agent.storage.database import (
    create_tables,
    get_engine,
    get_session,
    init_db,
)
from commerce_agent.storage.models import (
    AuditRecord,
    ConversationLog,
    Order,
    Product,
    RefundRecord,
    User,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def engine():
    """Provide an in-memory SQLite engine with all tables created."""
    eng = get_engine("sqlite:///:memory:")
    create_tables(eng)
    return eng


@pytest.fixture()
def session(engine):
    """Provide a SQLModel session backed by an in-memory database."""
    with get_session(engine) as sess:
        yield sess


def _make_user(name: str = "Alice", level: str = "normal") -> User:
    return User(name=name, level=level)


def _make_product(
    name: str = "Widget",
    category: str = "electronics",
    price: float = 99.9,
) -> Product:
    return Product(name=name, category=category, price=price)


def _make_order(user_id: str, total: float = 199.8) -> Order:
    return Order(
        user_id=user_id,
        total_amount=total,
        items_json=json.dumps([{"product_id": "p1", "qty": 2}]),
        address_json=json.dumps({"city": "Shanghai"}),
    )


def _make_refund(order_id: str, user_id: str, amount: float = 50.0) -> RefundRecord:
    return RefundRecord(order_id=order_id, user_id=user_id, reason="defective", amount=amount)


# ===================================================================
# Database utility tests
# ===================================================================


@pytest.mark.unit
class TestDatabaseUtilities:
    def test_get_engine_returns_engine(self) -> None:
        eng = get_engine("sqlite:///:memory:")
        assert eng is not None

    def test_create_tables_idempotent(self) -> None:
        eng = get_engine("sqlite:///:memory:")
        create_tables(eng)
        create_tables(eng)  # should not raise

    def test_init_db_returns_engine(self) -> None:
        eng = init_db("sqlite:///:memory:")
        assert eng is not None

    def test_get_session_commit_on_clean_exit(self, engine) -> None:
        with get_session(engine) as sess:
            user = User(name="SessionTest")
            sess.add(user)
        # Verify persisted
        with get_session(engine) as sess:
            result = sess.exec(select(User).where(User.name == "SessionTest")).one()
            assert result.name == "SessionTest"

    def test_get_session_rollback_on_exception(self, engine) -> None:
        user_name = "_rollback_test_"
        with pytest.raises(ValueError):
            with get_session(engine) as sess:
                sess.add(User(name=user_name))
                raise ValueError("force rollback")
        with get_session(engine) as sess:
            result = sess.exec(select(User).where(User.name == user_name)).first()
            assert result is None


# ===================================================================
# User CRUD
# ===================================================================


@pytest.mark.unit
class TestUserCRUD:
    def test_create_user(self, session) -> None:
        user = _make_user()
        session.add(user)
        session.flush()
        assert user.id  # UUID generated
        assert user.level == "normal"
        assert isinstance(user.created_at, datetime)

    def test_read_user(self, session) -> None:
        user = _make_user(name="Bob")
        session.add(user)
        session.flush()
        fetched = session.get(User, user.id)
        assert fetched is not None
        assert fetched.name == "Bob"

    def test_update_user(self, session) -> None:
        user = _make_user()
        session.add(user)
        session.flush()
        user.level = "vip"
        user.email = "bob@example.com"
        session.add(user)
        session.flush()
        fetched = session.get(User, user.id)
        assert fetched is not None
        assert fetched.level == "vip"
        assert fetched.email == "bob@example.com"

    def test_delete_user(self, session) -> None:
        user = _make_user(name="ToDelete")
        session.add(user)
        session.flush()
        uid = user.id
        session.delete(user)
        session.flush()
        assert session.get(User, uid) is None

    def test_user_optional_fields(self, session) -> None:
        user = User(name="NoPhone")
        session.add(user)
        session.flush()
        fetched = session.get(User, user.id)
        assert fetched is not None
        assert fetched.phone is None
        assert fetched.email is None

    def test_user_default_level(self, session) -> None:
        user = User(name="DefaultLevel")
        session.add(user)
        session.flush()
        fetched = session.get(User, user.id)
        assert fetched is not None
        assert fetched.level == "normal"


# ===================================================================
# Product CRUD
# ===================================================================


@pytest.mark.unit
class TestProductCRUD:
    def test_create_product(self, session) -> None:
        product = _make_product()
        session.add(product)
        session.flush()
        assert product.id
        assert product.is_active is True
        assert product.stock == 0
        assert product.rating == 0.0

    def test_read_product(self, session) -> None:
        product = _make_product(name="Gadget")
        session.add(product)
        session.flush()
        fetched = session.get(Product, product.id)
        assert fetched is not None
        assert fetched.name == "Gadget"
        assert fetched.category == "electronics"

    def test_update_product_stock(self, session) -> None:
        product = _make_product()
        session.add(product)
        session.flush()
        product.stock = 50
        product.price = 89.9
        session.add(product)
        session.flush()
        fetched = session.get(Product, product.id)
        assert fetched is not None
        assert fetched.stock == 50
        assert fetched.price == 89.9

    def test_delete_product(self, session) -> None:
        product = _make_product(name="ToDeactivate")
        session.add(product)
        session.flush()
        pid = product.id
        session.delete(product)
        session.flush()
        assert session.get(Product, pid) is None

    def test_product_optional_fields(self, session) -> None:
        product = Product(name="Bare", category="books", price=10.0)
        session.add(product)
        session.flush()
        fetched = session.get(Product, product.id)
        assert fetched is not None
        assert fetched.original_price is None
        assert fetched.description is None
        assert fetched.image_url is None
        assert fetched.tags == ""

    def test_product_tags_comma_separated(self, session) -> None:
        product = Product(
            name="Tagged",
            category="electronics",
            price=5.0,
            tags="sale,hot,new",
        )
        session.add(product)
        session.flush()
        fetched = session.get(Product, product.id)
        assert fetched is not None
        tags = fetched.tags.split(",")
        assert tags == ["sale", "hot", "new"]


# ===================================================================
# Order CRUD and status transitions
# ===================================================================


@pytest.mark.unit
class TestOrderCRUD:
    def test_create_order(self, session) -> None:
        user = _make_user()
        session.add(user)
        session.flush()
        order = _make_order(user.id)
        session.add(order)
        session.flush()
        assert order.id
        assert order.status == "pending"

    def test_order_status_transition(self, session) -> None:
        user = _make_user()
        session.add(user)
        session.flush()
        order = _make_order(user.id)
        session.add(order)
        session.flush()

        for status in ("paid", "shipped", "delivered"):
            order.status = status
            session.add(order)
            session.flush()
            fetched = session.get(Order, order.id)
            assert fetched is not None
            assert fetched.status == status

    def test_order_cancel_status(self, session) -> None:
        user = _make_user()
        session.add(user)
        session.flush()
        order = _make_order(user.id)
        session.add(order)
        session.flush()
        order.status = "cancelled"
        session.add(order)
        session.flush()
        fetched = session.get(Order, order.id)
        assert fetched is not None
        assert fetched.status == "cancelled"

    def test_order_items_json(self, session) -> None:
        user = _make_user()
        session.add(user)
        session.flush()
        items = [{"product_id": "abc", "qty": 3, "price": 29.9}]
        order = Order(
            user_id=user.id,
            total_amount=89.7,
            items_json=json.dumps(items),
        )
        session.add(order)
        session.flush()
        fetched = session.get(Order, order.id)
        assert fetched is not None
        parsed = json.loads(fetched.items_json)
        assert len(parsed) == 1
        assert parsed[0]["qty"] == 3

    def test_order_address_json(self, session) -> None:
        user = _make_user()
        session.add(user)
        session.flush()
        addr = {"city": "Beijing", "district": "Haidian", "street": "Zhongguancun"}
        order = Order(
            user_id=user.id,
            total_amount=100.0,
            items_json="[]",
            address_json=json.dumps(addr),
        )
        session.add(order)
        session.flush()
        fetched = session.get(Order, order.id)
        assert fetched is not None
        parsed = json.loads(fetched.address_json)
        assert parsed["city"] == "Beijing"


# ===================================================================
# RefundRecord status flow
# ===================================================================


@pytest.mark.unit
class TestRefundRecordCRUD:
    def test_create_refund(self, session) -> None:
        user = _make_user()
        session.add(user)
        session.flush()
        order = _make_order(user.id)
        session.add(order)
        session.flush()
        refund = _make_refund(order.id, user.id)
        session.add(refund)
        session.flush()
        assert refund.id
        assert refund.status == "pending"

    def test_refund_status_flow(self, session) -> None:
        user = _make_user()
        session.add(user)
        session.flush()
        order = _make_order(user.id)
        session.add(order)
        session.flush()
        refund = _make_refund(order.id, user.id)
        session.add(refund)
        session.flush()

        for status in ("approved", "processing", "completed"):
            refund.status = status
            session.add(refund)
            session.flush()
            fetched = session.get(RefundRecord, refund.id)
            assert fetched is not None
            assert fetched.status == status

    def test_refund_rejected(self, session) -> None:
        user = _make_user()
        session.add(user)
        session.flush()
        order = _make_order(user.id)
        session.add(order)
        session.flush()
        refund = _make_refund(order.id, user.id)
        session.add(refund)
        session.flush()
        refund.status = "rejected"
        session.add(refund)
        session.flush()
        fetched = session.get(RefundRecord, refund.id)
        assert fetched is not None
        assert fetched.status == "rejected"


# ===================================================================
# ConversationLog
# ===================================================================


@pytest.mark.unit
class TestConversationLogCRUD:
    def test_create_and_read(self, session) -> None:
        log = ConversationLog(
            session_id="sess-001",
            role="user",
            content="I want to check my order",
        )
        session.add(log)
        session.flush()
        assert log.id
        fetched = session.get(ConversationLog, log.id)
        assert fetched is not None
        assert fetched.content == "I want to check my order"

    def test_query_by_session_id(self, session) -> None:
        for i in range(3):
            session.add(
                ConversationLog(
                    session_id="sess-A",
                    role="user" if i % 2 == 0 else "assistant",
                    content=f"msg-{i}",
                )
            )
        session.add(
            ConversationLog(session_id="sess-B", role="user", content="other")
        )
        session.flush()

        results = session.exec(
            select(ConversationLog).where(ConversationLog.session_id == "sess-A")
        ).all()
        assert len(results) == 3
        for r in results:
            assert r.session_id == "sess-A"

    def test_optional_fields(self, session) -> None:
        log = ConversationLog(
            session_id="sess-002",
            role="assistant",
            content="result",
            intent_name="query_order",
            tool_calls_json=json.dumps([{"tool": "query_order"}]),
            tokens_used=120,
            latency_ms=350,
        )
        session.add(log)
        session.flush()
        fetched = session.get(ConversationLog, log.id)
        assert fetched is not None
        assert fetched.intent_name == "query_order"
        assert fetched.tokens_used == 120
        assert fetched.latency_ms == 350

    def test_user_id_index(self, session) -> None:
        session.add(
            ConversationLog(
                session_id="s1",
                user_id="user-123",
                role="user",
                content="hi",
            )
        )
        session.flush()
        results = session.exec(
            select(ConversationLog).where(ConversationLog.user_id == "user-123")
        ).all()
        assert len(results) == 1


# ===================================================================
# AuditRecord
# ===================================================================


@pytest.mark.unit
class TestAuditRecordCRUD:
    def test_create_and_read(self, session) -> None:
        record = AuditRecord(
            session_id="sess-010",
            action_type="tool_call",
            action_detail="query_order executed",
        )
        session.add(record)
        session.flush()
        fetched = session.get(AuditRecord, record.id)
        assert fetched is not None
        assert fetched.risk_level == "low"

    def test_risk_level_filtering(self, session) -> None:
        for level in ("low", "medium", "high", "critical"):
            session.add(
                AuditRecord(
                    session_id="sess-risk",
                    action_type="security_event",
                    action_detail=f"event-{level}",
                    risk_level=level,
                )
            )
        session.flush()

        high_or_above = session.exec(
            select(AuditRecord).where(AuditRecord.risk_level.in_(["high", "critical"]))
        ).all()
        assert len(high_or_above) == 2

        low = session.exec(
            select(AuditRecord).where(AuditRecord.risk_level == "low")
        ).all()
        assert len(low) == 1

    def test_optional_metadata(self, session) -> None:
        record = AuditRecord(
            session_id="sess-meta",
            action_type="permission_check",
            action_detail="refund requires approval",
            risk_level="medium",
            metadata_json=json.dumps({"role": "customer", "threshold": 500}),
        )
        session.add(record)
        session.flush()
        fetched = session.get(AuditRecord, record.id)
        assert fetched is not None
        meta = json.loads(fetched.metadata_json)
        assert meta["threshold"] == 500

    def test_session_id_filter(self, session) -> None:
        for sid in ("sess-a", "sess-b"):
            session.add(
                AuditRecord(
                    session_id=sid,
                    action_type="tool_call",
                    action_detail=f"call for {sid}",
                )
            )
        session.flush()
        results = session.exec(
            select(AuditRecord).where(AuditRecord.session_id == "sess-a")
        ).all()
        assert len(results) == 1


# ===================================================================
# Relationships: User -> Orders, Order -> Refunds
# ===================================================================


@pytest.mark.unit
class TestRelationships:
    def test_user_has_multiple_orders(self, session) -> None:
        user = _make_user(name="MultiOrder")
        session.add(user)
        session.flush()
        for i in range(3):
            session.add(
                Order(
                    user_id=user.id,
                    total_amount=float(i * 100),
                    items_json=json.dumps([{"item": i}]),
                )
            )
        session.flush()

        orders = session.exec(
            select(Order).where(Order.user_id == user.id)
        ).all()
        assert len(orders) == 3

    def test_order_has_refunds(self, session) -> None:
        user = _make_user()
        session.add(user)
        session.flush()
        order = _make_order(user.id)
        session.add(order)
        session.flush()
        for reason in ("defective", "wrong item"):
            session.add(
                RefundRecord(
                    order_id=order.id,
                    user_id=user.id,
                    reason=reason,
                    amount=25.0,
                )
            )
        session.flush()

        refunds = session.exec(
            select(RefundRecord).where(RefundRecord.order_id == order.id)
        ).all()
        assert len(refunds) == 2
        reasons = {r.reason for r in refunds}
        assert reasons == {"defective", "wrong item"}


# ===================================================================
# Field constraints
# ===================================================================


@pytest.mark.unit
class TestFieldConstraints:
    def test_product_price_non_negative(self, session) -> None:
        """Product with price >= 0 should be accepted."""
        product = Product(name="Freebie", category="promo", price=0.0)
        session.add(product)
        session.flush()
        fetched = session.get(Product, product.id)
        assert fetched is not None
        assert fetched.price == 0.0

    def test_product_positive_price(self, session) -> None:
        product = Product(name="Paid", category="general", price=49.99)
        session.add(product)
        session.flush()
        fetched = session.get(Product, product.id)
        assert fetched is not None
        assert fetched.price > 0

    def test_user_level_values(self, session) -> None:
        for level in ("normal", "vip", "svip"):
            user = User(name=f"Lvl-{level}", level=level)
            session.add(user)
            session.flush()
            fetched = session.get(User, user.id)
            assert fetched is not None
            assert fetched.level == level

    def test_order_status_values(self, session) -> None:
        user = _make_user()
        session.add(user)
        session.flush()
        for status in ("pending", "paid", "shipped", "delivered", "cancelled", "refunded"):
            order = Order(
                user_id=user.id,
                total_amount=10.0,
                items_json="[]",
                status=status,
            )
            session.add(order)
            session.flush()
            fetched = session.get(Order, order.id)
            assert fetched is not None
            assert fetched.status == status
