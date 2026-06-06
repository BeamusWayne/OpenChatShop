"""PostgreSQL + pgvector VectorStore backend (V2.0 module 2, feat-045).

Implements the feat-044 VectorStore over Postgres with a pgvector HNSW cosine
index, so semantic search scales past the in-memory linear scan. The table and
index are created by Alembic migration 004; this class only reads/writes via
SQLAlchemy ``text()`` SQL, so it needs no pgvector *Python* package — only a
Postgres with the ``vector`` extension (the docker pgvector/pgvector image).

``build_vector_store`` selects this backend when a DATABASE_URL is configured
and falls back to the in-memory store otherwise.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text as _sql

from open_chat_shop.core.semantic_search import (
    InMemoryVectorStore,
    SearchResult,
    VectorStore,
)

_TABLE = "vector_documents"


def _format_vector(vector: list[float]) -> str:
    """Render a vector as a pgvector literal: ``[0.1,0.2,0.3]``."""
    return "[" + ",".join(str(x) for x in vector) + "]"


class PgVectorStore(VectorStore):
    """VectorStore backed by Postgres + pgvector (HNSW cosine index)."""

    def __init__(self, engine: Any, dimension: int = 384) -> None:
        # Engine only; the schema is owned by migration 004. No connection is
        # opened here, so construction (and the factory) needs no live DB.
        self._engine = engine
        self._dimension = dimension

    def add(self, intent: str, text: str, vector: list[float]) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                _sql(
                    f"INSERT INTO {_TABLE} (intent, content, embedding) "
                    "VALUES (:intent, :content, CAST(:emb AS vector))"
                ),
                {"intent": intent, "content": text, "emb": _format_vector(vector)},
            )

    def search(self, query_vector: list[float], top_k: int = 3) -> list[SearchResult]:
        emb = _format_vector(query_vector)
        with self._engine.connect() as conn:
            rows = conn.execute(
                _sql(
                    f"SELECT intent, content, "
                    "1 - (embedding <=> CAST(:emb AS vector)) AS score "
                    f"FROM {_TABLE} ORDER BY embedding <=> CAST(:emb AS vector) LIMIT :k"
                ),
                {"emb": emb, "k": top_k},
            ).all()
        return [
            SearchResult(intent=r.intent, score=float(r.score), text=r.content)
            for r in rows
        ]

    def get_intents(self) -> list[str]:
        with self._engine.connect() as conn:
            rows = conn.execute(_sql(f"SELECT DISTINCT intent FROM {_TABLE}")).all()
        return [r.intent for r in rows]

    def clear(self, intent: str | None = None) -> None:
        with self._engine.begin() as conn:
            if intent is None:
                conn.execute(_sql(f"DELETE FROM {_TABLE}"))
            else:
                conn.execute(
                    _sql(f"DELETE FROM {_TABLE} WHERE intent = :intent"),
                    {"intent": intent},
                )


def build_vector_store(database_url: str | None, dimension: int = 384) -> VectorStore:
    """Return a pgvector store when *database_url* is set, else in-memory."""
    if not database_url:
        return InMemoryVectorStore(dimension)
    from sqlalchemy import create_engine

    return PgVectorStore(create_engine(database_url), dimension)
