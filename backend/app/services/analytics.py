"""Cookie-less website analytics: forward page views to Plausible or Umami.

Why the API forwards instead of a script tag on the page:
- no third-party JavaScript (faster pages, no `<script>` rendered by React, simpler CSP),
- nothing is stored on the visitor's device, so no cookie banner is needed for it,
- we control exactly what leaves our server: a page PATH (never query strings, which can hold
  tokens like /reset-password?token=...), the referrer's ORIGIN only, and the browser name.
The visitor's IP and user agent go to the provider only so it can count unique visitors
(both providers hash them with a daily salt and don't store them). Mention the provider in the
privacy policy (docs/LEGAL_TEMPLATES.md).
"""

from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx

from app.core.config import Settings
from app.core.logging import get_logger
from app.schemas.analytics import AnalyticsEvent

logger = get_logger(__name__)


@dataclass(frozen=True)
class Visitor:
    """Who sent the event (only used to count unique visitors, never stored by us)."""

    ip: str
    user_agent: str


def clean_path(path: str) -> str:
    """Only the path: drop query string and fragment."""
    return path.split("#", 1)[0].split("?", 1)[0] or "/"


def clean_referrer(referrer: str | None) -> str | None:
    """Only the origin of the referring page (https://example.com), or None."""
    if not referrer:
        return None
    parts = urlsplit(referrer)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    port = f":{parts.port}" if parts.port else ""
    return f"{parts.scheme}://{parts.hostname}{port}"


class AnalyticsSender(Protocol):
    """Sends one event to the analytics provider. Tests use a fake."""

    async def send(self, event: AnalyticsEvent, visitor: Visitor) -> None:
        """Forward the event. Must never raise."""
        ...


class _HttpSender:
    """Shared HTTP code for both providers."""

    def __init__(
        self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._host = settings.analytics_host
        self._site = settings.analytics_site
        self._app_url = settings.app_url
        self._transport = transport

    def _payload(self, event: AnalyticsEvent) -> tuple[str, dict[str, Any]]:
        raise NotImplementedError

    async def send(self, event: AnalyticsEvent, visitor: Visitor) -> None:
        """POST the event; log (never raise) on failure."""
        url, body = self._payload(event)
        headers = {"User-Agent": visitor.user_agent, "X-Forwarded-For": visitor.ip}
        try:
            async with httpx.AsyncClient(timeout=5.0, transport=self._transport) as client:
                response = await client.post(url, json=body, headers=headers)
            if response.status_code >= 400:
                logger.warning("analytics_rejected", status=response.status_code)
        except httpx.HTTPError as exc:
            logger.warning("analytics_unreachable", error=type(exc).__name__)


class PlausibleSender(_HttpSender):
    """Plausible Events API: POST {host}/api/event."""

    def _payload(self, event: AnalyticsEvent) -> tuple[str, dict[str, Any]]:
        body: dict[str, Any] = {
            "name": event.name,
            "url": self._app_url + clean_path(event.path),
            "domain": self._site,
        }
        referrer = clean_referrer(event.referrer)
        if referrer:
            body["referrer"] = referrer
        if event.props:
            body["props"] = event.props
        return f"{self._host}/api/event", body


class UmamiSender(_HttpSender):
    """Umami API: POST {host}/api/send."""

    def _payload(self, event: AnalyticsEvent) -> tuple[str, dict[str, Any]]:
        payload: dict[str, Any] = {
            "website": self._site,
            "hostname": urlsplit(self._app_url).hostname or "",
            "url": clean_path(event.path),
            "referrer": clean_referrer(event.referrer) or "",
        }
        if event.name != "pageview":
            payload["name"] = event.name
            if event.props:
                payload["data"] = event.props
        return f"{self._host}/api/send", {"type": "event", "payload": payload}


def build_analytics_sender(settings: Settings) -> AnalyticsSender | None:
    """The configured sender, or None when analytics is off."""
    if settings.analytics_provider == "plausible":
        return PlausibleSender(settings)
    if settings.analytics_provider == "umami":
        return UmamiSender(settings)
    return None
