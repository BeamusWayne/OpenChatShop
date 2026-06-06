"""Tests for UserPersona storage (feat-052, V2.0 module 3 foundation).

A persona is a per-user (user_id) bag of profile attributes that persists across
sessions, so later turns can be personalised. The repository upserts by merging,
so feat-053's async extraction can add tags incrementally without clobbering.
Both the in-memory and the database backend honour the same contract.
"""
from __future__ import annotations

import pytest
from sqlmodel import SQLModel, create_engine

from open_chat_shop.storage.persona import (
    DatabasePersonaRepository,
    InMemoryPersonaRepository,
    PersonaRepository,
)


def _memory_repo() -> PersonaRepository:
    return InMemoryPersonaRepository()


def _db_repo() -> PersonaRepository:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return DatabasePersonaRepository(engine)


@pytest.fixture(params=[_memory_repo, _db_repo], ids=["memory", "db"])
def repo(request) -> PersonaRepository:
    return request.param()


@pytest.mark.unit
class TestPersonaRepositoryContract:
    def test_get_missing_returns_none(self, repo: PersonaRepository) -> None:
        assert repo.get("nobody") is None

    def test_upsert_then_get(self, repo: PersonaRepository) -> None:
        repo.upsert("u1", {"size": "L", "price_sensitive": "true"})
        assert repo.get("u1") == {"size": "L", "price_sensitive": "true"}

    def test_upsert_merges_keeping_old_keys(self, repo: PersonaRepository) -> None:
        repo.upsert("u1", {"size": "L"})
        merged = repo.upsert("u1", {"style": "日系极简"})
        assert merged == {"size": "L", "style": "日系极简"}
        assert repo.get("u1") == {"size": "L", "style": "日系极简"}

    def test_upsert_overwrites_same_key(self, repo: PersonaRepository) -> None:
        repo.upsert("u1", {"size": "L"})
        repo.upsert("u1", {"size": "XL"})
        assert repo.get("u1") == {"size": "XL"}

    def test_get_returns_a_copy(self, repo: PersonaRepository) -> None:
        repo.upsert("u1", {"size": "L"})
        got = repo.get("u1")
        assert got is not None
        got["size"] = "MUTATED"
        assert repo.get("u1") == {"size": "L"}  # stored value untouched


@pytest.mark.unit
def test_db_persists_across_sessions() -> None:
    # The DB repo opens a fresh session per call; an upsert must survive into a
    # later, independent get (that is the whole point of cross-session memory).
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    DatabasePersonaRepository(engine).upsert("u9", {"vip": "true"})
    assert DatabasePersonaRepository(engine).get("u9") == {"vip": "true"}
