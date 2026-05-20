"""Unit tests for main.py entry point."""
from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest


def _get_app() -> FastAPI:
    os.environ.setdefault("DEV_MODE", "true")
    from main import create_main_app

    return create_main_app()


def _client() -> TestClient:
    return TestClient(_get_app())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestMainApp:
    def test_create_app_returns_fastapi_instance(self) -> None:
        app = _get_app()
        assert isinstance(app, FastAPI)

    def test_auth_check_rejects_without_credentials(self) -> None:
        """Server must refuse to start without JWT_SECRET_KEY or API_KEY."""
        original_dev = os.environ.pop("DEV_MODE", None)
        original_jwt = os.environ.pop("JWT_SECRET_KEY", None)
        original_api = os.environ.pop("API_KEY", None)
        try:
            with pytest.raises(SystemExit):
                from main import _check_auth_config
                _check_auth_config()
        finally:
            if original_dev is not None:
                os.environ["DEV_MODE"] = original_dev
            if original_jwt is not None:
                os.environ["JWT_SECRET_KEY"] = original_jwt
            if original_api is not None:
                os.environ["API_KEY"] = original_api

    def test_auth_check_passes_with_api_key(self) -> None:
        """Server starts fine when API_KEY is set."""
        original_dev = os.environ.pop("DEV_MODE", None)
        original_api = os.environ.pop("API_KEY", None)
        try:
            os.environ["API_KEY"] = "test-key-123"
            from main import _check_auth_config
            _check_auth_config()
        finally:
            os.environ.pop("API_KEY", None)
            if original_dev is not None:
                os.environ["DEV_MODE"] = original_dev
            if original_api is not None:
                os.environ["API_KEY"] = original_api

    def test_auth_check_passes_with_dev_mode(self) -> None:
        """Server starts in DEV_MODE without auth credentials."""
        original_jwt = os.environ.pop("JWT_SECRET_KEY", None)
        original_api = os.environ.pop("API_KEY", None)
        try:
            os.environ["DEV_MODE"] = "true"
            from main import _check_auth_config
            _check_auth_config()
        finally:
            os.environ.pop("DEV_MODE", None)
            if original_jwt is not None:
                os.environ["JWT_SECRET_KEY"] = original_jwt
            if original_api is not None:
                os.environ["API_KEY"] = original_api

    def test_health_endpoint_returns_ok(self) -> None:
        client = _client()
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert "version" in body

    def test_chat_endpoint_returns_response(self) -> None:
        client = _client()
        resp = client.post(
            "/api/v1/chat",
            json={
                "session_id": "test-session-1",
                "content": "你好",
                "channel": "web",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "message_type" in body
        assert "payload" in body
        assert "text_fallback" in body

    def test_app_has_cors_middleware(self) -> None:
        app = _get_app()
        # FastAPI wraps middleware in Middleware objects; check the cls attribute
        middleware_classes = [
            getattr(m, "cls", type(m)).__name__ for m in app.user_middleware
        ]
        has_cors = any("CORS" in cls for cls in middleware_classes)
        assert has_cors, f"CORS middleware not found. Got: {middleware_classes}"

    def test_static_files_mounted(self) -> None:
        app = _get_app()
        from pathlib import Path
        from starlette.routing import Mount

        static_dir = Path(__file__).parent.parent.parent / "static"
        if static_dir.is_dir():
            has_root_mount = any(
                isinstance(r, Mount) and r.path == ""
                for r in app.routes
            )
            assert has_root_mount, "Expected static file mount when static/ dir exists"
