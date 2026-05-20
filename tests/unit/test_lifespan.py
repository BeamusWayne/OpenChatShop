"""Tests for FastAPI lifespan (graceful shutdown) integration."""
from __future__ import annotations

from fastapi.testclient import TestClient

from open_chat_shop.api.app import create_app


def test_health_endpoint_returns_200():
    """Verify /health still returns 200 with the lifespan-enabled app."""
    client = TestClient(create_app())
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "version" in body
