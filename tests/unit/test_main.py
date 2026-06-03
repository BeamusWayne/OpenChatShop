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


class TestResilienceWiring:
    """Regression for the main.py resilience wiring bug.

    The original code wrapped ``provider.generate`` — a method that does not
    exist on LLMProvider (only chat/stream/embed). Evaluating it raised
    AttributeError, which an ``except Exception: pass`` swallowed, silently
    skipping ``orchestrator.set_provider`` in the same try block. Result: zero
    circuit-breaker/retry protection AND the orchestrator never received the
    provider. These tests encode *why* the wiring must target ``chat`` and why
    ``set_provider`` must run unconditionally.
    """

    def test_set_provider_runs_and_chat_is_wrapped_with_retry(self, monkeypatch) -> None:
        import asyncio

        import main as main_mod
        from open_chat_shop.core.provider import LLMProvider
        from open_chat_shop.core.types import (
            LLMResponse,
            ProviderCapabilities,
        )

        calls = {"n": 0}

        class _FlakyProvider(LLMProvider):
            name = "flaky"

            async def chat(self, messages, tools=None, config=None):
                calls["n"] += 1
                if calls["n"] <= 2:
                    raise TimeoutError("transient")
                return LLMResponse(content="ok")

            async def stream(self, messages, tools=None, config=None):
                yield  # pragma: no cover

            async def embed(self, texts):
                return [[0.0] for _ in texts]

            def get_capabilities(self):
                return ProviderCapabilities(
                    tool_calling=False,
                    streaming=False,
                    vision=False,
                    max_context_tokens=8192,
                )

            def estimate_tokens(self, text):
                return len(text)

        fake = _FlakyProvider()
        monkeypatch.setattr(main_mod, "_build_provider", lambda: fake)
        monkeypatch.setenv("DEV_MODE", "true")

        orch = main_mod.build_orchestrator()

        # 1. set_provider must have run (the bug skipped it entirely).
        assert orch._provider is fake, "orchestrator never received the provider"

        # 2. chat must be wrapped — instance attribute now shadows the method.
        assert fake.chat.__name__ == "_resilient_chat", "chat was not wrapped"

        # 3. The wrapper must retry transient TimeoutError and then succeed,
        #    proving the resilience layer is actually on the call path.
        result = asyncio.run(fake.chat([]))
        assert result.content == "ok"
        assert calls["n"] == 3, "expected 2 retries before success"
