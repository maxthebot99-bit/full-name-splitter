"""Lightweight ASGI middleware: CSRF header check on /api/* routes.

Cloudflare Access blocks most cross-origin attacks at the edge, but a stolen
JWT cookie used from a malicious tab in the user's authenticated browser
would otherwise sail through. Requiring a custom header (``X-Requested-With:
full-name-splitter``) on every /api/* request closes that vector — cross-origin
JS cannot add custom headers without a preflight, and our CORS rejects
preflights from unknown origins.

The React app sets this header on every fetch via the shared API helper.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

CSRF_HEADER_NAME = "x-requested-with"
CSRF_HEADER_VALUE = "full-name-splitter"


class CSRFCheckMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        if path.startswith("/api/"):
            # Allow GETs to /api/health, /api/events/*, and /api/download/*
            # without the X-Requested-With header. Reasoning:
            #   * health: no auth at all (k8s probes, etc.)
            #   * events: SSE via EventSource cannot set custom headers
            #   * download: <a href download> from the React UI cannot set
            #     custom headers either; the session_id in the URL is a UUID4
            #     and the response is read-only, so the CSRF surface is
            #     "victim accidentally downloads their OWN cleaned data" —
            #     not an attack worth defending against.
            #
            # All state-changing routes (upload, run, dry-run, cancel) still
            # require the header, which keeps cookies-from-evil-tab attacks
            # from triggering Grok runs.
            csrf_exempt = (
                path == "/api/health"
                or path.startswith("/api/events/")
                or path.startswith("/api/download/")
            )
            if not csrf_exempt:
                if request.headers.get(CSRF_HEADER_NAME, "").lower() != CSRF_HEADER_VALUE:
                    return JSONResponse(
                        {"error": "missing or invalid X-Requested-With header"},
                        status_code=400,
                    )
        return await call_next(request)
