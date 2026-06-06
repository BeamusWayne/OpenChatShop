"""JWT and API Key authentication middleware."""
from __future__ import annotations

import hmac
import logging
from typing import Any

from fastapi import Request
from jose import JWTError
from jose import jwt as jose_jwt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)


class AuthMiddleware(BaseHTTPMiddleware):
    """Validates JWT tokens or API keys on protected endpoints."""

    def __init__(
        self,
        app: Any,
        jwt_secret: str | None = None,
        api_key: str | None = None,
        public_paths: list[str] | None = None,
    ) -> None:
        super().__init__(app)
        self._jwt_secret = jwt_secret
        self._api_key = api_key
        self._public_paths = public_paths or [
            "/health",
            "/health/ready",
            "/metrics",
            "/docs",
            "/openapi.json",
            "/",
        ]
        # Static assets live ONLY under these mount prefixes (the React build
        # emits hashed JS/CSS into /static and /assets). The bypass MUST be
        # scoped to these prefixes — never a global suffix test on the full
        # path — or any protected route with an attacker-shaped trailing path
        # parameter ending in .js/.css/.html/.ico (e.g.
        # /api/v1/agent/history/<id>.js) would skip authentication entirely.
        self._static_prefixes = ("/static/", "/assets/")
        # A short allowlist of well-known root-level static files served by the
        # SPA mount at "/". These are concrete filenames, not a suffix wildcard.
        self._static_root_files = frozenset(
            {"/favicon.ico", "/manifest.json", "/robots.txt", "/index.html"}
        )

    async def dispatch(self, request: Request, call_next: Any) -> Any:
        # Allow public paths without auth (prefix match for /health, /metrics, /docs)
        path = request.url.path
        for prefix in self._public_paths:
            if path == prefix or path.startswith(prefix + "/"):
                return await call_next(request)

        # Allow static files — scoped to the real static mount prefixes and a
        # concrete root-file allowlist. Deliberately NOT a global path.endswith()
        # on extensions, which would let a crafted trailing path parameter
        # (".../something.js") bypass auth on protected endpoints.
        if path.startswith(self._static_prefixes) or path in self._static_root_files:
            return await call_next(request)

        # If no auth configured, allow all
        if not self._jwt_secret and not self._api_key:
            return await call_next(request)

        # Check API Key. This is a SERVICE-level credential (a shared server
        # secret), NOT a per-user identity — so, unlike the JWT path below, it
        # deliberately does not bind request.state.user_id. Per-user,
        # ownership-sensitive actions (order tools) must authenticate with a JWT,
        # whose verified `sub` becomes the authoritative user_id; a service
        # holding the API key is trusted to act on behalf of users. Customer-
        # facing chat must therefore use JWT, not the API key, or order-ownership
        # falls back to the advisory client-supplied user_id (audit: hardening).
        api_key_header = request.headers.get("X-API-Key")
        if self._api_key and api_key_header is not None and hmac.compare_digest(
            api_key_header, self._api_key
        ):
            return await call_next(request)

        # Check JWT Bearer token
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer ") and self._jwt_secret:
            token = auth_header[7:]
            try:
                payload = jose_jwt.decode(
                    token, self._jwt_secret, algorithms=["HS256"]
                )
                # Bind the *server-verified* identity to the request so handlers
                # never have to trust a client-supplied user_id. This is the
                # source of truth for order-ownership checks (prevents IDOR).
                request.state.user_id = payload.get("sub")
                return await call_next(request)
            except JWTError:
                logger.warning("JWT validation failed for path %s", request.url.path)

        # Auth required but no valid credentials
        return JSONResponse(
            status_code=401,
            content={"detail": "Authentication required"},
        )
