"""SQLModel business models for the OpenChatShop e-commerce dialogue system.

Defines persistent data structures mapped to database tables:
  - User: customer accounts with tier levels
  - Product: catalogue items with pricing and stock
  - Order: purchase orders with status tracking
  - RefundRecord: refund requests linked to orders
  - ConversationLog: per-message conversation history
  - AuditRecord: security and compliance audit trail
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


def _utc_now() -> datetime:
    """Return the current UTC time (timezone-aware)."""
    return datetime.now(timezone.utc)


def _new_id() -> str:
    """Generate a new hex UUID string for primary keys."""
    return uuid.uuid4().hex


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------


class User(SQLModel, table=True):
    """A registered customer account."""

    id: str = Field(default_factory=_new_id, primary_key=True)
    name: str
    phone: Optional[str] = Field(default=None)
    email: Optional[str] = Field(default=None)
    level: str = Field(default="normal")  # normal / vip / svip
    created_at: datetime = Field(default_factory=_utc_now)
    last_active_at: datetime = Field(default_factory=_utc_now)


# ---------------------------------------------------------------------------
# Product
# ---------------------------------------------------------------------------


class Product(SQLModel, table=True):
    """A product listing in the catalogue."""

    id: str = Field(default_factory=_new_id, primary_key=True)
    name: str
    category: str
    price: float
    original_price: Optional[float] = Field(default=None)
    stock: int = Field(default=0)
    description: Optional[str] = Field(default=None)
    image_url: Optional[str] = Field(default=None)
    rating: float = Field(default=0.0)
    tags: str = Field(default="")  # comma-separated
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=_utc_now)


# ---------------------------------------------------------------------------
# Order
# ---------------------------------------------------------------------------


class Order(SQLModel, table=True):
    """A purchase order placed by a user."""

    id: str = Field(default_factory=_new_id, primary_key=True)
    user_id: str = Field(foreign_key="user.id")
    status: str = Field(default="pending")  # pending/paid/shipped/delivered/cancelled/refunded
    total_amount: float
    items_json: str  # JSON-encoded list of order items
    address_json: Optional[str] = Field(default=None)  # JSON-encoded address
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)


# ---------------------------------------------------------------------------
# RefundRecord
# ---------------------------------------------------------------------------


class RefundRecord(SQLModel, table=True):
    """A refund request tied to an order."""

    id: str = Field(default_factory=_new_id, primary_key=True)
    order_id: str = Field(foreign_key="order.id")
    user_id: str = Field(foreign_key="user.id")
    reason: str
    amount: float
    status: str = Field(default="pending")  # pending/approved/rejected/processing/completed
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)


# ---------------------------------------------------------------------------
# ConversationLog
# ---------------------------------------------------------------------------


class ConversationLog(SQLModel, table=True):
    """A single message in a conversation session."""

    id: str = Field(default_factory=_new_id, primary_key=True)
    session_id: str = Field(index=True)
    user_id: Optional[str] = Field(default=None, index=True)
    role: str  # user / assistant / system / tool
    content: str
    intent_name: Optional[str] = Field(default=None)
    tool_calls_json: Optional[str] = Field(default=None)
    tokens_used: int = Field(default=0)
    latency_ms: int = Field(default=0)
    created_at: datetime = Field(default_factory=_utc_now)


# ---------------------------------------------------------------------------
# AuditRecord
# ---------------------------------------------------------------------------


class AuditRecord(SQLModel, table=True):
    """Security and compliance audit trail entry."""

    id: str = Field(default_factory=_new_id, primary_key=True)
    session_id: str = Field(index=True)
    user_id: Optional[str] = Field(default=None)
    action_type: str  # tool_call / security_event / permission_check
    action_detail: str
    risk_level: str = Field(default="low")  # low / medium / high / critical
    metadata_json: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=_utc_now)
