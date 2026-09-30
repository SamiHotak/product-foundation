"""Sentry error reports (backend API and Celery worker).

Off unless SENTRY_DSN is set. Privacy first (the privacy policy says so, keep it true):

- no cookies, no request bodies, no user email or IP (`send_default_pii=False` + scrubbing;
  email and IPv4 patterns inside error texts are replaced too),
- expected errors (wrong password, limit reached, 404 ...) are not reported, only real bugs,
- every event carries the release (image tag) and the request id, so a report can be matched
  to one log line.
"""

import re
from typing import Any

import sentry_sdk
import structlog
from sentry_sdk.scrubber import DEFAULT_DENYLIST, EventScrubber
from sentry_sdk.transport import Transport

from app.core.config import Settings

# Extra keys that must never leave the server (on top of Sentry's own list).
_EXTRA_DENYLIST = [
    *DEFAULT_DENYLIST,
    "session",
    "email",
    "api_key",
    "stripe_signature",
    "invite_token",
    "reset_token",
]


_EMAIL = re.compile(r"[A-Za-z0-9._%+'-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


def _clean_text(value: Any) -> Any:
    """Recursively replace email addresses and IPv4 addresses in every string of the event.

    Error messages can contain them (a database error names the duplicate email, a mail provider
    error names the recipient). Keys named "email" are already removed by the scrubber; this catches
    the ones inside texts. It is pattern based: it removes the usual forms, not every one.
    """
    if isinstance(value, str):
        return _IPV4.sub("[ip]", _EMAIL.sub("[email]", value))
    if isinstance(value, dict):
        return {key: _clean_text(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clean_text(item) for item in value]
    return value


def scrub_event(event: dict[str, Any], _hint: dict[str, Any]) -> dict[str, Any] | None:
    """Last line of defence before an event is sent: drop bodies, cookies and user data."""
    request = event.get("request")
    if isinstance(request, dict):
        for key in ("data", "cookies", "query_string"):
            request.pop(key, None)
        headers = request.get("headers")
        if isinstance(headers, dict):
            for name in list(headers):
                if name.lower() in {"cookie", "authorization", "x-forwarded-for", "x-real-ip"}:
                    headers.pop(name, None)
    event.pop("user", None)
    request_id = structlog.contextvars.get_contextvars().get("request_id")
    if request_id:
        event.setdefault("tags", {})["request_id"] = request_id
    cleaned: dict[str, Any] = _clean_text(event)
    return cleaned


def init_sentry(settings: Settings, *, component: str, transport: Transport | None = None) -> bool:
    """Start Sentry when configured. `component` is "api" or "worker". Returns True if on.

    `transport` is only for tests (collects events instead of sending them).
    """
    if not settings.sentry_dsn:
        return False
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment.value,
        release=settings.sentry_release or None,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        send_default_pii=False,
        max_request_body_size="never",
        include_local_variables=False,  # local variables can hold passwords or tokens
        event_scrubber=EventScrubber(denylist=_EXTRA_DENYLIST, recursive=True),
        before_send=scrub_event,  # type: ignore[arg-type]
        transport=transport,
    )
    sentry_sdk.set_tag("component", component)
    return True
