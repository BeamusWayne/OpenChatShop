"""JWT and API Key authentication middleware."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import Request
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

    async def dispatch(self, request: Request, call_next: Any) -> Any:
        # Allow public paths without auth (prefix match for /health, /metrics, /docs)
        path = request.url.path
        for prefix in self._public_paths:
            if path == prefix or path.startswith(prefix + "/"):
                return await call_next(request)

        # Allow static files
        if request.url.path.startswith("/assets") or request.url.path.endswith(
            (".js", ".css", ".html", ".ico")
        ):
            return await call_next(request)

        # If no auth configured, allow all
        if not self._jwt_secret and not self._api_key:
            return await call_next(request)

        # Check API Key
        api_key_header = request.headers.get("X-API-Key")
        if self._api_key and api_key_header == self._api_key:
            return await call_next(request)

        # Check JWT Bearer token
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer ") and self._jwt_secret:
            token = auth_header[7:]
            try:
                from jose import jwt as jose_jwt

                jose_jwt.decode(token, self._jwt_secret, algorithms=["HS256"])
                # Token is valid
                return await call_next(request)
            except Exception:
                logger.warning("JWT validation failed for path %s", request.url.path)

        # Auth required but no valid credentials
        return JSONResponse(
            status_code=401,
            content={"detail": "Authentication required"},
        )
