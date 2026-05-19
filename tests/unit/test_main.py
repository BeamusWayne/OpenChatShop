"""Unit tests for main.py entry point."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _get_app() -> FastAPI:
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
        # The app should have route mounts. Check that a /static mount exists.
        # Even if static/ dir doesn't exist, we check the route structure.
        mount_paths = [
            route.path
            for route in app.routes
            if hasattr(route, "path") and "static" in route.path
        ]
        # If static dir exists, we expect a /static mount.
        # If not, we just verify the app doesn't crash (mount_paths may be empty).
        # The key requirement is that the code handles both cases.
        from pathlib import Path

        static_dir = Path(__file__).parent.parent.parent / "static"
        if static_dir.is_dir():
            assert len(mount_paths) > 0, "Expected /static mount when static/ dir exists"
