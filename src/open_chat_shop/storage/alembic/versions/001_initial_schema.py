"""Initial schema — all six OpenChatShop tables.

Revision ID: 001
Revises: None
Create Date: 2026-05-19
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: str | None = None
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "user",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("phone", sa.String(), nullable=True),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("level", sa.String(), nullable=False, server_default="normal"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_active_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "product",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("original_price", sa.Float(), nullable=True),
        sa.Column("stock", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("image_url", sa.String(), nullable=True),
        sa.Column("rating", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("tags", sa.String(), nullable=False, server_default=""),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "order",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("user_id", sa.String(32), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("total_amount", sa.Float(), nullable=False),
        sa.Column("items_json", sa.String(), nullable=False),
        sa.Column("address_json", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "refundrecord",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("order_id", sa.String(32), sa.ForeignKey("order.id"), nullable=False),
        sa.Column("user_id", sa.String(32), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "conversationlog",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("session_id", sa.String(), nullable=False, index=True),
        sa.Column("user_id", sa.String(), nullable=True, index=True),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("content", sa.String(), nullable=False),
        sa.Column("intent_name", sa.String(), nullable=True),
        sa.Column("tool_calls_json", sa.String(), nullable=True),
        sa.Column("tokens_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "auditrecord",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("session_id", sa.String(), nullable=False, index=True),
        sa.Column("user_id", sa.String(), nullable=True),
        sa.Column("action_type", sa.String(), nullable=False),
        sa.Column("action_detail", sa.String(), nullable=False),
        sa.Column("risk_level", sa.String(), nullable=False, server_default="low"),
        sa.Column("metadata_json", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("auditrecord")
    op.drop_table("conversationlog")
    op.drop_table("refundrecord")
    op.drop_table("order")
    op.drop_table("product")
    op.drop_table("user")
