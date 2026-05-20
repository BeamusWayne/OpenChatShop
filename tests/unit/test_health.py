"""Tests for health and readiness endpoints."""
from __future__ import annotations

from fastapi.testclient import TestClient

from open_chat_shop.api.app import create_app


def test_health_returns_200():
    """The basic liveness probe should always return 200."""
    client = TestClient(create_app())
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "version" in body


def test_readiness_returns_checks_structure():
    """The readiness probe should return a checks dict with database and redis."""
    client = TestClient(create_app())
    resp = client.get("/health/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "checks" in body
    assert "database" in body["checks"]
    assert "redis" in body["checks"]
    assert "uptime_seconds" in body
    assert "version" in body
