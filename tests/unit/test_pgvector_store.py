"""Tests for the pgvector VectorStore backend (feat-045, V2.0 module 2).

NOTE ON SCOPE: there is no local Postgres/pgvector, so the live add/search
round-trip is NOT exercised here — it runs under docker/CI (the
pgvector/pgvector image). What is verified locally: the DATABASE_URL switch, ABC
conformance, the vector literal formatting, and that migration 004 declares the
HNSW index + vector column + extension.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from open_chat_shop.core.semantic_search import InMemoryVectorStore, VectorStore
from open_chat_shop.storage.pgvector_store import (
    PgVectorStore,
    _format_vector,
    build_vector_store,
)

_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "src/open_chat_shop/storage/alembic/versions/004_add_vector_documents.py"
)


@pytest.mark.unit
class TestPgVectorStore:
    def test_format_vector_is_pgvector_literal(self) -> None:
        assert _format_vector([0.1, 0.2, 0.3]) == "[0.1,0.2,0.3]"

    def test_pgvector_store_is_a_vector_store(self) -> None:
        # Construct without connecting (engine is lazy); no DB needed.
        store = build_vector_store("postgresql://u:p@localhost/db")
        assert isinstance(store, PgVectorStore)
        assert isinstance(store, VectorStore)

    def test_factory_falls_back_to_memory_without_url(self) -> None:
        assert isinstance(build_vector_store(None), InMemoryVectorStore)
        assert isinstance(build_vector_store(""), InMemoryVectorStore)


@pytest.mark.unit
class TestMigration004:
    def test_migration_declares_hnsw_index_and_vector_column(self) -> None:
        source = _MIGRATION.read_text()
        assert "CREATE EXTENSION IF NOT EXISTS vector" in source
        assert "vector(384)" in source
        assert "USING hnsw" in source
        assert "vector_cosine_ops" in source

    def test_migration_chains_from_003(self) -> None:
        import importlib

        mod = importlib.import_module(
            "open_chat_shop.storage.alembic.versions.004_add_vector_documents"
        )
        assert mod.revision == "004"
        assert mod.down_revision == "003"
        assert callable(mod.upgrade)
        assert callable(mod.downgrade)
