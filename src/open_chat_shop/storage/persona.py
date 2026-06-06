"""User persona storage — cross-session profile (V2.0 module 3, feat-052).

A persona is a per-user bag of profile attributes ("size"->"L",
"price_sensitive"->"true", "style"->"日系极简") that persists across sessions so
later conversations can be personalised. ``upsert`` merges, so feat-053's async
extraction can accumulate tags over time without clobbering existing ones.

Attributes are stored JSON-encoded in a single column, mirroring the
``items_json`` convention in models.py.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import cast

from sqlmodel import Field, Session, SQLModel


def _utc_now() -> datetime:
    return datetime.now(UTC)


class UserPersona(SQLModel, table=True):
    """Persisted per-user profile attributes."""

    user_id: str = Field(primary_key=True)
    attributes_json: str = Field(default="{}")
    updated_at: datetime = Field(default_factory=_utc_now)


class PersonaRepository(ABC):
    """Contract for reading and merging user personas."""

    @abstractmethod
    def get(self, user_id: str) -> dict[str, str] | None:
        """Return the user's attributes, or None if no persona exists."""

    @abstractmethod
    def upsert(self, user_id: str, attributes: dict[str, str]) -> dict[str, str]:
        """Merge *attributes* into the user's persona; return the full persona."""


class InMemoryPersonaRepository(PersonaRepository):
    """In-process persona store (default, zero-config)."""

    def __init__(self) -> None:
        self._store: dict[str, dict[str, str]] = {}

    def get(self, user_id: str) -> dict[str, str] | None:
        stored = self._store.get(user_id)
        return dict(stored) if stored is not None else None

    def upsert(self, user_id: str, attributes: dict[str, str]) -> dict[str, str]:
        merged = {**self._store.get(user_id, {}), **attributes}
        self._store[user_id] = merged
        return dict(merged)


class DatabasePersonaRepository(PersonaRepository):
    """SQLModel-backed persona store."""

    def __init__(self, engine: object) -> None:
        self._engine = engine

    def get(self, user_id: str) -> dict[str, str] | None:
        with Session(self._engine) as session:  # type: ignore[arg-type]
            row = session.get(UserPersona, user_id)
            if row is None:
                return None
            return cast("dict[str, str]", json.loads(row.attributes_json))

    def upsert(self, user_id: str, attributes: dict[str, str]) -> dict[str, str]:
        with Session(self._engine) as session:  # type: ignore[arg-type]
            row = session.get(UserPersona, user_id)
            current: dict[str, str] = json.loads(row.attributes_json) if row else {}
            merged = {**current, **attributes}
            payload = json.dumps(merged, ensure_ascii=False)
            if row is None:
                session.add(UserPersona(user_id=user_id, attributes_json=payload))
            else:
                row.attributes_json = payload
                row.updated_at = _utc_now()
                session.add(row)
            session.commit()
            return merged
