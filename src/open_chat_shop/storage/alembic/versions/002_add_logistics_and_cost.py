"""Add logisticsrecord and costrecord tables.

Revision ID: 002
Revises: 001
Create Date: 2026-05-20
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "002"
down_revision: str | None = "001"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "logisticsrecord",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("order_id", sa.String(32), sa.ForeignKey("order.id"), nullable=False, index=True),
        sa.Column("carrier", sa.String(), nullable=False),
        sa.Column("tracking_number", sa.String(), nullable=False),
        sa.Column("timeline_json", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "costrecord",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("costrecord")
    op.drop_table("logisticsrecord")
