"""Add user_persona table (V2.0 module 3, feat-052).

Revision ID: 003
Revises: 002
Create Date: 2026-06-06
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: str | None = "002"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "userpersona",
        sa.Column("user_id", sa.String(), primary_key=True),
        sa.Column("attributes_json", sa.String(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("userpersona")
