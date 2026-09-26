"""CSRF protection for cookie-authenticated requests.

Two layers:
1. The session cookie is SameSite=Lax, so browsers don't send it on cross-site POSTs.
2. This middleware rejects state-changing requests (POST, PUT, PATCH, DELETE) that carry
   the session cookie but come from a page on another origin (checked with the Origin
   header, or Referer when Origin is missing).
Requests without the cookie (health checks, API keys in phase 2B) are not affected.
"""

import json
from urllib.parse import urlsplit

from starlette.types import ASGIApp, Receive, Scope, Send

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _origin_of(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}" if parts.scheme and parts.netloc else ""


class CsrfMiddleware:
    """Pure ASGI middleware (works with streaming responses)."""

    def __init__(self, app: ASGIApp, *, cookie_name: str, allowed_origins: set[str]) -> None:
        self.app = app
        self.cookie_name = cookie_name.encode()
        self.allowed = {o.rstrip("/") for o in allowed_origins}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Block cross-origin, cookie-authenticated, state-changing requests."""
        if scope["type"] != "http" or scope["method"] in SAFE_METHODS:
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        has_session = self.cookie_name + b"=" in headers.get(b"cookie", b"")
        if has_session:
            origin = headers.get(b"origin", b"").decode("latin-1")
            if not origin or origin == "null":
                origin = _origin_of(headers.get(b"referer", b"").decode("latin-1"))
            if origin and origin not in self.allowed:
                await self._reject(scope, send)
                return
        await self.app(scope, receive, send)

    async def _reject(self, scope: Scope, send: Send) -> None:
        request_id = scope.get("state", {}).get("request_id")
        body = json.dumps(
            {
                "error": {
                    "code": "csrf_failed",
                    "message": "This request came from another website and was blocked.",
                    "request_id": request_id,
                }
            }
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 403,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": body})
