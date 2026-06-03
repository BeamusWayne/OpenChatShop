"""Unit tests for JWT and API Key authentication middleware."""
from __future__ import annotations

import os
from unittest.mock import patch

from fastapi.testclient import TestClient
from jose import jwt as jose_jwt

from open_chat_shop.api.app import create_app

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_jwt_token(payload: dict, secret: str) -> str:
    """Create a signed JWT token for testing."""
    return jose_jwt.encode(payload, secret, algorithm="HS256")


# ---------------------------------------------------------------------------
# Public paths — no auth required regardless of configuration
# ---------------------------------------------------------------------------


class TestPublicPaths:
    """Public endpoints remain accessible without any credentials."""

    def test_health_accessible_without_auth(self) -> None:
        """Health endpoint is always public."""
        with patch.dict(os.environ, {"JWT_SECRET_KEY": "secret", "API_KEY": "key123"}):
            client = TestClient(create_app())
            resp = client.get("/health")
            assert resp.status_code == 200

    def test_root_accessible_without_auth(self) -> None:
        """Root path is public."""
        with patch.dict(os.environ, {"JWT_SECRET_KEY": "secret", "API_KEY": "key123"}):
            client = TestClient(create_app())
            resp = client.get("/")
            assert resp.status_code in (200, 404)  # 404 if no root handler

    def test_docs_accessible_without_auth(self) -> None:
        """Docs path is public."""
        with patch.dict(os.environ, {"JWT_SECRET_KEY": "secret", "API_KEY": "key123"}):
            client = TestClient(create_app())
            resp = client.get("/docs")
            assert resp.status_code == 200

    def test_openapi_json_accessible_without_auth(self) -> None:
        """OpenAPI schema is public."""
        with patch.dict(os.environ, {"JWT_SECRET_KEY": "secret", "API_KEY": "key123"}):
            client = TestClient(create_app())
            resp = client.get("/openapi.json")
            assert resp.status_code == 200


# ---------------------------------------------------------------------------
# No auth configured — all endpoints open
# ---------------------------------------------------------------------------


class TestNoAuthConfigured:
    """When no secrets are set, all endpoints are accessible."""

    def test_chat_accessible_without_auth_when_no_secret(self) -> None:
        """Chat endpoint allows access when JWT_SECRET_KEY is empty."""
        with patch.dict(os.environ, {"JWT_SECRET_KEY": "", "API_KEY": ""}):
            client = TestClient(create_app())
            resp = client.post(
                "/api/v1/chat",
                json={"session_id": "s1", "content": "hello"},
            )
            # 503 means auth passed but no orchestrator — that is correct
            assert resp.status_code == 503


# ---------------------------------------------------------------------------
# Protected paths — JWT_SECRET_KEY is set
# ---------------------------------------------------------------------------


class TestJWTAuth:
    """Protected endpoints require valid JWT when JWT_SECRET_KEY is configured."""

    def test_protected_endpoint_rejects_no_credentials(self) -> None:
        """Request without Authorization header returns 401."""
        with patch.dict(os.environ, {"JWT_SECRET_KEY": "test-secret", "API_KEY": ""}):
            client = TestClient(create_app())
            resp = client.post(
                "/api/v1/chat",
                json={"session_id": "s1", "content": "hello"},
            )
            assert resp.status_code == 401

    def test_protected_endpoint_rejects_invalid_jwt(self) -> None:
        """Request with wrong JWT secret returns 401."""
        with patch.dict(os.environ, {"JWT_SECRET_KEY": "test-secret", "API_KEY": ""}):
            token = _make_jwt_token({"sub": "user1"}, "wrong-secret")
            client = TestClient(create_app())
            resp = client.post(
                "/api/v1/chat",
                json={"session_id": "s1", "content": "hello"},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 401

    def test_protected_endpoint_accepts_valid_jwt(self) -> None:
        """Request with valid JWT passes auth and reaches the endpoint."""
        with patch.dict(os.environ, {"JWT_SECRET_KEY": "test-secret", "API_KEY": ""}):
            token = _make_jwt_token({"sub": "user1"}, "test-secret")
            client = TestClient(create_app())
            resp = client.post(
                "/api/v1/chat",
                json={"session_id": "s1", "content": "hello"},
                headers={"Authorization": f"Bearer {token}"},
            )
            # 503 = auth passed, no orchestrator
            assert resp.status_code == 503

    def test_protected_endpoint_rejects_expired_jwt(self) -> None:
        """Request with expired JWT returns 401."""
        with patch.dict(os.environ, {"JWT_SECRET_KEY": "test-secret", "API_KEY": ""}):
            token = _make_jwt_token(
                {"sub": "user1", "exp": 1},  # exp=1 is far in the past
                "test-secret",
            )
            client = TestClient(create_app())
            resp = client.post(
                "/api/v1/chat",
                json={"session_id": "s1", "content": "hello"},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 401

    def test_protected_endpoint_rejects_malformed_bearer(self) -> None:
        """Request with malformed Authorization header returns 401."""
        with patch.dict(os.environ, {"JWT_SECRET_KEY": "test-secret", "API_KEY": ""}):
            client = TestClient(create_app())
            resp = client.post(
                "/api/v1/chat",
                json={"session_id": "s1", "content": "hello"},
                headers={"Authorization": "Bearer not-a-real-token"},
            )
            assert resp.status_code == 401


# ---------------------------------------------------------------------------
# API Key auth
# ---------------------------------------------------------------------------


class TestAPIKeyAuth:
    """Protected endpoints accept valid API key via X-API-Key header."""

    def test_valid_api_key_grants_access(self) -> None:
        """Request with correct X-API-Key passes auth."""
        with patch.dict(
            os.environ, {"JWT_SECRET_KEY": "secret", "API_KEY": "my-api-key"}
        ):
            client = TestClient(create_app())
            resp = client.post(
                "/api/v1/chat",
                json={"session_id": "s1", "content": "hello"},
                headers={"X-API-Key": "my-api-key"},
            )
            # 503 = auth passed, no orchestrator
            assert resp.status_code == 503

    def test_invalid_api_key_rejected(self) -> None:
        """Request with wrong X-API-Key returns 401."""
        with patch.dict(
            os.environ, {"JWT_SECRET_KEY": "secret", "API_KEY": "my-api-key"}
        ):
            client = TestClient(create_app())
            resp = client.post(
                "/api/v1/chat",
                json={"session_id": "s1", "content": "hello"},
                headers={"X-API-Key": "wrong-key"},
            )
            assert resp.status_code == 401

    def test_api_key_alone_without_jwt_secret(self) -> None:
        """API Key works even when JWT_SECRET_KEY is not set."""
        with patch.dict(os.environ, {"JWT_SECRET_KEY": "", "API_KEY": "my-api-key"}):
            client = TestClient(create_app())
            resp = client.post(
                "/api/v1/chat",
                json={"session_id": "s1", "content": "hello"},
                headers={"X-API-Key": "my-api-key"},
            )
            # 503 = auth passed, no orchestrator
            assert resp.status_code == 503

    def test_no_api_key_header_rejected(self) -> None:
        """Request without X-API-Key header is rejected when API_KEY is set."""
        with patch.dict(os.environ, {"JWT_SECRET_KEY": "", "API_KEY": "my-api-key"}):
            client = TestClient(create_app())
            resp = client.post(
                "/api/v1/chat",
                json={"session_id": "s1", "content": "hello"},
            )
            assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Static files bypass
# ---------------------------------------------------------------------------


class TestStaticFilesBypass:
    """Static asset paths bypass authentication."""

    def test_js_file_bypasses_auth(self) -> None:
        """Requests for .js files skip authentication."""
        with patch.dict(os.environ, {"JWT_SECRET_KEY": "secret", "API_KEY": "key123"}):
            client = TestClient(create_app())
            resp = client.get("/static/app.js")
            # 404 is fine — we just verify auth did not block it (would be 401)
            assert resp.status_code in (200, 404)

    def test_css_file_bypasses_auth(self) -> None:
        """Requests for .css files skip authentication."""
        with patch.dict(os.environ, {"JWT_SECRET_KEY": "secret", "API_KEY": "key123"}):
            client = TestClient(create_app())
            resp = client.get("/static/style.css")
            assert resp.status_code in (200, 404)

    def test_assets_path_bypasses_auth(self) -> None:
        """Requests under /assets skip authentication."""
        with patch.dict(os.environ, {"JWT_SECRET_KEY": "secret", "API_KEY": "key123"}):
            client = TestClient(create_app())
            resp = client.get("/assets/logo.png")
            assert resp.status_code in (200, 404)
