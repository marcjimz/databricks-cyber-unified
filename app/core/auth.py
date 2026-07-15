"""OBO (On-Behalf-Of) authentication middleware.

Extracts the user's access token from the X-Forwarded-Access-Token header
injected by the Databricks Apps proxy. Falls back to DATABRICKS_TOKEN env
var for local development.
"""

from __future__ import annotations

import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class OBOMiddleware(BaseHTTPMiddleware):
    """Extract OBO token and user identity from Databricks Apps proxy headers."""

    async def dispatch(self, request: Request, call_next) -> Response:
        # Skip auth for non-API routes (static files, health checks)
        if not request.url.path.startswith("/api/") or request.url.path == "/api/health":
            return await call_next(request)

        # Extract OBO token from proxy headers
        token = request.headers.get("X-Forwarded-Access-Token")

        # Local dev fallback
        if not token:
            token = os.environ.get("DATABRICKS_TOKEN", "")

        # Store on request state for downstream use
        request.state.obo_token = token
        request.state.user_email = request.headers.get(
            "X-Forwarded-Email", os.environ.get("DATABRICKS_USER_EMAIL", "local-dev@example.com")
        )
        request.state.user_name = request.headers.get(
            "X-Forwarded-Preferred-Username", os.environ.get("DATABRICKS_USER_NAME", "Local Dev")
        )

        return await call_next(request)
