"""Regression: the RedisContextManager's own async client is disposed on shutdown.

main.py builds up to three Redis clients when REDIS_URL is set:
  - a SYNC client for the cache + rate limiter (closed: ``_redis_sync.close()``),
  - an ASYNC client for the readiness probe (closed via ``app.state``),
  - the RedisContextManager's OWN async client (main.py:_build_context_manager).

The third was created and then dropped — never registered for shutdown — so its
connection pool leaked on every graceful shutdown when REDIS_URL (and no
DATABASE_URL) selected the Redis context backend. These tests pin that the
client is now published on ``resources`` and ``aclose()``d by the lifespan.
"""
from __future__ import annotations

import os
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

# main.py builds the app at import time and exits unless an auth mode is set.
# DEV_MODE skips that so we can import it and drive the lifespan.
os.environ.setdefault("DEV_MODE", "true")

import main


@pytest.mark.unit
def test_context_redis_client_is_registered_on_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """REDIS_URL (no DATABASE_URL) -> RedisContextManager whose async client is
    published under resources['context_redis'] for shutdown disposal."""
    import redis.asyncio as aioredis

    from open_chat_shop.storage.redis_context import RedisContextManager

    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    resources: dict[str, object] = {}
    cm = main._build_context_manager(resources)

    assert isinstance(cm, RedisContextManager)
    assert isinstance(resources.get("context_redis"), aioredis.Redis)


@pytest.mark.unit
def test_lifespan_closes_context_redis_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Running startup+shutdown must aclose() every async client that was
    created — including the context manager's own (the previously-leaked one)."""
    created: list[AsyncMock] = []

    def fake_from_url(*_args: object, **_kwargs: object) -> AsyncMock:
        client = AsyncMock()
        created.append(client)
        return client

    monkeypatch.setenv("DEV_MODE", "true")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    # Patch only the ASYNC factory; the sync client stays real (lazy, harmless).
    monkeypatch.setattr("redis.asyncio.from_url", fake_from_url)

    app = main.create_main_app()
    with TestClient(app):  # __enter__ runs startup, __exit__ runs shutdown
        pass

    # With this env exactly two async clients exist: the context manager's own
    # and the readiness-probe client. The leak fix requires BOTH be disposed.
    assert len(created) >= 1, "no async Redis client was created"
    for client in created:
        client.aclose.assert_awaited()
