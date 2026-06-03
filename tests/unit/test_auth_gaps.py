"""Tests for auth middleware public paths and WebSocket agent token validation."""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient

from open_chat_shop.api.app import create_app


class TestPublicPaths:
    """Verify health/metrics endpoints are accessible without auth."""

    @patch.dict(os.environ, {"JWT_SECRET_KEY": "test-secret", "API_KEY": ""})
    def test_health_accessible_without_auth(self):
        client = TestClient(create_app())
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    @patch.dict(os.environ, {"JWT_SECRET_KEY": "test-secret", "API_KEY": ""})
    def test_health_ready_accessible_without_auth(self):
        client = TestClient(create_app())
        resp = client.get("/health/ready")
        assert resp.status_code == 200

    @patch.dict(os.environ, {"JWT_SECRET_KEY": "test-secret", "API_KEY": ""})
    def test_metrics_accessible_without_auth(self):
        client = TestClient(create_app())
        resp = client.get("/metrics")
        assert resp.status_code != 401

    @patch.dict(os.environ, {"JWT_SECRET_KEY": "test-secret", "API_KEY": ""})
    def test_chat_requires_auth(self):
        client = TestClient(create_app())
        resp = client.post(
            "/api/v1/chat",
            json={"session_id": "s1", "content": "hello"},
        )
        assert resp.status_code == 401


class TestAgentWebSocketToken:
    """Verify agent WebSocket validates AGENT_TOKEN when configured."""

    @pytest.mark.skip(reason="Sync TestClient blocks on WS with async callbacks")
    def test_ws_agent_no_token_required_when_not_configured(self):
        app = create_app(agent_token=None)
        client = TestClient(app)
        with client.websocket_connect("/ws/agent/agent-test?name=Test") as ws:
            data = ws.receive_json()
            assert data["type"] == "queue_state"

    @pytest.mark.skip(reason="Sync TestClient blocks on WS close-before-accept")
    def test_ws_agent_rejects_wrong_token(self):
        app = create_app(agent_token="correct-secret")
        client = TestClient(app)
        with pytest.raises(WebSocketDisconnect), client.websocket_connect(
            "/ws/agent/agent-test?token=wrong"
        ):
            pass

    @pytest.mark.skip(reason="Sync TestClient blocks on WS close-before-accept")
    def test_ws_agent_accepts_correct_token(self):
        app = create_app(agent_token="correct-secret")
        client = TestClient(app)
        with client.websocket_connect(
            "/ws/agent/agent-test?token=correct-secret&name=Test"
        ) as ws:
            data = ws.receive_json()
            assert data["type"] == "queue_state"
