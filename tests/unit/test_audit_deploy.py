
"""Regression tests for the DEPLOY audit cluster.

Each test here encodes WHY a fixed behaviour matters and FAILS against the
pre-fix code:

* CRITICAL — AuthMiddleware static-file bypass: a global ``path.endswith()``
  on .js/.css/.html/.ico let an attacker append a benign extension to a
  protected route's trailing path parameter and skip authentication.
* CRITICAL — gunicorn multi-worker default: per-process in-memory handoff /
  socket state silently breaks human handoff under >1 worker, so single
  worker must be the safe default.
* CRITICAL — prod compose never injected the agent secret: the shipped
  container left AGENT_SECRET / AGENT_TOKEN unset, fully bypassing agent
  REST + WS auth.
* LOW — container HEALTHCHECK probed a shallow always-200 /health, so a
  wedged-but-listening process stayed "healthy" and never recycled.
"""
from __future__ import annotations

import os
import runpy
from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from open_chat_shop.api.auth import AuthMiddleware

_REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# CRITICAL — AuthMiddleware static-file bypass (src/open_chat_shop/api/auth.py)
# ---------------------------------------------------------------------------


def _protected_app() -> FastAPI:
    """A minimal app guarded by AuthMiddleware with a protected route that
    takes an attacker-controlled trailing path parameter."""
    app = FastAPI()
    app.add_middleware(AuthMiddleware, jwt_secret="test-secret", api_key="test-key")

    @app.get("/api/v1/agent/history/{session_id}")
    async def history(session_id: str, request: Request) -> dict[str, str]:
        # If we reach here, auth was satisfied (or wrongly bypassed).
        return {"session_id": session_id}

    @app.get("/static/{path:path}")
    async def static_file(path: str) -> dict[str, str]:
        return {"served": path}

    @app.get("/assets/{path:path}")
    async def asset_file(path: str) -> dict[str, str]:
        return {"served": path}

    return app


class TestStaticBypassIsScoped:
    """The static exemption must be scoped to the static mount prefixes, not a
    global suffix test on the whole request path."""

    def test_protected_route_with_js_suffix_is_not_bypassed(self) -> None:
        """A crafted ``…/<id>.js`` on a protected endpoint must still require
        auth. Pre-fix this returned 200 (auth bypassed) — a real auth-bypass
        primitive against /api/v1/agent/history/{session_id}."""
        client = TestClient(_protected_app())
        resp = client.get("/api/v1/agent/history/victim-session.js")
        assert resp.status_code == 401

    @pytest.mark.parametrize("ext", [".js", ".css", ".html", ".ico"])
    def test_protected_route_with_any_static_extension_is_not_bypassed(
        self, ext: str
    ) -> None:
        """None of the formerly-allowlisted extensions may unlock a protected
        route via a trailing path parameter."""
        client = TestClient(_protected_app())
        resp = client.get(f"/api/v1/agent/history/victim{ext}")
        assert resp.status_code == 401

    def test_protected_route_with_valid_api_key_still_works(self) -> None:
        """Sanity: a properly authenticated request reaches the handler."""
        client = TestClient(_protected_app())
        resp = client.get(
            "/api/v1/agent/history/my-session",
            headers={"X-API-Key": "test-key"},
        )
        assert resp.status_code == 200
        assert resp.json()["session_id"] == "my-session"

    def test_real_static_under_static_prefix_still_bypasses(self) -> None:
        """Legitimate static assets under /static must still skip auth (the
        SPA build serves hashed JS/CSS there)."""
        client = TestClient(_protected_app())
        resp = client.get("/static/app.123abc.js")
        assert resp.status_code == 200

    def test_real_static_under_assets_prefix_still_bypasses(self) -> None:
        """Legitimate static assets under /assets must still skip auth."""
        client = TestClient(_protected_app())
        resp = client.get("/assets/logo.png")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# CRITICAL — gunicorn single-worker safe default (gunicorn.conf.py)
# ---------------------------------------------------------------------------


class TestGunicornSingleWorkerDefault:
    """Per-process in-memory handoff/socket state means >1 worker silently
    breaks human handoff, so single worker must be the default."""

    def _load_conf(self, env: dict[str, str]) -> dict[str, object]:
        # Execute gunicorn.conf.py as a fresh module under controlled env and
        # capture its module-level globals (workers, worker_class, …).
        old = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        # Remove any inherited GUNICORN_WORKERS unless the test sets it.
        if "GUNICORN_WORKERS" not in env:
            os.environ.pop("GUNICORN_WORKERS", None)
        try:
            return runpy.run_path(str(_REPO_ROOT / "gunicorn.conf.py"))
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_default_workers_is_one(self) -> None:
        """With GUNICORN_WORKERS unset the config must default to a single
        worker — pre-fix it defaulted to cpu_count()*2+1 (multi-worker)."""
        conf = self._load_conf({})
        assert conf["workers"] == 1

    def test_explicit_override_is_honoured(self) -> None:
        """An operator can still opt into more workers (loudly warned), so the
        env override must take effect."""
        conf = self._load_conf({"GUNICORN_WORKERS": "3"})
        assert conf["workers"] == 3

    def test_uses_uvicorn_worker(self) -> None:
        conf = self._load_conf({})
        assert conf["worker_class"] == "uvicorn.workers.UvicornWorker"


@pytest.mark.unit
def test_gunicorn_conf_documents_multiworker_hazard() -> None:
    """The single-worker requirement must be loudly documented in-file so the
    next operator does not re-enable multi-worker blindly."""
    content = (_REPO_ROOT / "gunicorn.conf.py").read_text()
    assert "production-hardening-audit.md" in content
    assert "human handoff" in content.lower()


# ---------------------------------------------------------------------------
# CRITICAL — prod compose injects the agent secret (docker-compose.prod.yml)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_prod_compose_requires_agent_secret() -> None:
    """The agent REST gate reads AGENT_SECRET; it must be delivered to the
    container and be required (fail-closed) — pre-fix it was absent, so REST
    agent auth was bypassed in the shipped deploy."""
    content = (_REPO_ROOT / "docker-compose.prod.yml").read_text()
    assert "AGENT_SECRET=${AGENT_SECRET:?" in content


@pytest.mark.unit
def test_prod_compose_injects_agent_token_for_ws_gate() -> None:
    """The agent WebSocket gate reads a SEPARATE var (AGENT_TOKEN); without it
    the WS auth check is skipped. It must be sourced from the same secret so a
    single configured value activates both gates."""
    content = (_REPO_ROOT / "docker-compose.prod.yml").read_text()
    assert "AGENT_TOKEN=${AGENT_SECRET" in content


# ---------------------------------------------------------------------------
# LOW — container HEALTHCHECK validates readiness JSON (Dockerfile)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_dockerfile_healthcheck_probes_readiness_and_asserts_status() -> None:
    """The healthcheck must hit the deep /health/ready probe and assert the
    JSON status, so a wedged container (status != 'ok') is reported unhealthy
    and recycled — pre-fix it pinged shallow always-200 /health."""
    content = (_REPO_ROOT / "Dockerfile").read_text()
    assert "/health/ready" in content
    assert "status" in content
    # The shallow always-200 /health ping must no longer be the probe target.
    assert "urlopen('http://localhost:8000/health')" not in content
