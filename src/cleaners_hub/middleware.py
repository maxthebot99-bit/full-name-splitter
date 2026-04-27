"""Lightweight ASGI middleware: CSRF header check on /api/* routes.

Cloudflare Access blocks most cross-origin attacks at the edge, but a stolen
JWT cookie used from a malicious tab in the user's authenticated browser
would otherwise sail through. Requiring a custom header (``X-Requested-With:
cleaners-hub``) on every /api/* request closes that vector — cross-origin
JS cannot add custom headers without a preflight, and our CORS rejects
preflights from unknown origins.

The React app sets this header on every fetch via the shared API helper.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

CSRF_HEADER_NAME = "x-requested-with"
CSRF_HEADER_VALUE = "cleaners-hub"


class CSRFCheckMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        if path.startswith("/api/"):
            # Allow GETs to /api/health and /api/events without the header so
            # health checks and direct browser visits to SSE work; everything
            # state-changing requires the header.
            if path not in ("/api/health",) and not path.startswith("/api/events/"):
                if request.headers.get(CSRF_HEADER_NAME, "").lower() != CSRF_HEADER_VALUE:
                    return JSONResponse(
                        {"error": "missing or invalid X-Requested-With header"},
                        status_code=400,
                    )
        return await call_next(request)
