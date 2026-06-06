"""Add vector_documents table with a pgvector HNSW index (feat-045).

Postgres-only (requires the pgvector extension). Revision ID: 004; Revises: 003.
Create Date: 2026-06-06
"""
from __future__ import annotations

from alembic import op

revision: str = "004"
down_revision: str | None = "003"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        "CREATE TABLE IF NOT EXISTS vector_documents ("
        "id BIGSERIAL PRIMARY KEY, "
        "intent TEXT NOT NULL, "
        "content TEXT NOT NULL, "
        "embedding vector(384) NOT NULL)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_vector_documents_hnsw "
        "ON vector_documents USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS vector_documents")
