"""Cookie-less analytics: the endpoint, privacy cleaning, and both provider formats."""

import json

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.config import Environment, Settings
from app.core.rate_limit import MemoryRateLimiter, get_rate_limiter
from app.routers.analytics import get_analytics_sender
from app.schemas.analytics import AnalyticsEvent
from app.services.analytics import (
    PlausibleSender,
    UmamiSender,
    Visitor,
    build_analytics_sender,
    clean_path,
    clean_referrer,
)

UA = "Mozilla/5.0 (Windows NT 10.0) Chrome/140"


class FakeSender:
    """Records what would be sent."""

    def __init__(self) -> None:
        self.sent: list[tuple[AnalyticsEvent, Visitor]] = []

    async def send(self, event: AnalyticsEvent, visitor: Visitor) -> None:
        self.sent.append((event, visitor))


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "_env_file": None,
        "environment": Environment.TEST,
        "app_url": "https://app.example.com/",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


@pytest.fixture
def fake_sender(healthy_app: FastAPI) -> FakeSender:
    sender = FakeSender()
    healthy_app.dependency_overrides[get_analytics_sender] = lambda: sender
    healthy_app.dependency_overrides[get_rate_limiter] = MemoryRateLimiter
    return sender


# --- endpoint ------------------------------------------------------------------------------


async def test_off_by_default_answers_204_and_sends_nothing(client: AsyncClient) -> None:
    response = await client.post(
        "/api/analytics/event", json={"path": "/"}, headers={"user-agent": UA}
    )
    assert response.status_code == 204
    assert response.content == b""


async def test_page_view_is_forwarded(client: AsyncClient, fake_sender: FakeSender) -> None:
    response = await client.post(
        "/api/analytics/event",
        json={"path": "/pricing", "referrer": "https://news.example.org/a?b=c"},
        headers={"user-agent": UA},
    )
    assert response.status_code == 204
    assert len(fake_sender.sent) == 1
    event, visitor = fake_sender.sent[0]
    assert event.name == "pageview"
    assert event.path == "/pricing"
    assert visitor.user_agent == UA
    assert visitor.ip  # the test client's address


async def test_events_without_a_browser_are_ignored(
    client: AsyncClient, fake_sender: FakeSender
) -> None:
    response = await client.post(
        "/api/analytics/event", json={"path": "/"}, headers={"user-agent": ""}
    )
    assert response.status_code == 204
    assert fake_sender.sent == []


@pytest.mark.parametrize(
    "body",
    [
        {"path": "pricing"},  # must start with /
        {"path": "/" + "a" * 400},  # too long
        {"path": "/", "name": "Sign Up!"},  # event names: lowercase, digits, _
        {"path": "/", "props": {"k": "v" * 101}},  # value too long
        {"path": "/", "props": {f"k{i}": "v" for i in range(11)}},  # too many props
    ],
)
async def test_bad_events_are_rejected(
    client: AsyncClient, fake_sender: FakeSender, body: dict[str, object]
) -> None:
    response = await client.post("/api/analytics/event", json=body, headers={"user-agent": UA})
    assert response.status_code == 422
    assert fake_sender.sent == []


async def test_flooding_is_dropped_quietly(
    healthy_app: FastAPI, settings: Settings, fake_sender: FakeSender
) -> None:
    limited = settings.model_copy(update={"analytics_events_per_minute_per_ip": 3})
    from app.core.config import get_settings

    healthy_app.dependency_overrides[get_settings] = lambda: limited
    limiter = MemoryRateLimiter()
    healthy_app.dependency_overrides[get_rate_limiter] = lambda: limiter
    transport = ASGITransport(app=healthy_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        for _ in range(5):
            r = await c.post("/api/analytics/event", json={"path": "/"}, headers={"user-agent": UA})
            assert r.status_code == 204
    assert len(fake_sender.sent) == 3


# --- privacy cleaning ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("/reset-password?token=secret", "/reset-password"),
        ("/pricing#faq", "/pricing"),
        ("/a?b#c", "/a"),
        ("/", "/"),
        ("?x=1", "/"),
    ],
)
def test_clean_path_drops_query_and_fragment(raw: str, clean: str) -> None:
    assert clean_path(raw) == clean


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("https://news.example.org/story?id=7&email=a@b.c", "https://news.example.org"),
        ("http://localhost:3000/x", "http://localhost:3000"),
        ("javascript:alert(1)", None),
        ("not a url", None),
        ("", None),
        (None, None),
    ],
)
def test_clean_referrer_keeps_only_the_origin(raw: str | None, clean: str | None) -> None:
    assert clean_referrer(raw) == clean


# --- providers -----------------------------------------------------------------------------


def _capture() -> tuple[list[httpx.Request], httpx.MockTransport]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(202)

    return seen, httpx.MockTransport(handler)


async def test_plausible_format() -> None:
    settings = _settings(
        analytics_provider="plausible",
        analytics_host="https://plausible.io/",
        analytics_site="app.example.com",
    )
    seen, transport = _capture()
    sender = PlausibleSender(settings, transport=transport)
    event = AnalyticsEvent(
        name="signup",
        path="/signup?next=/x",
        referrer="https://google.com/search?q=me",
        props={"plan": "pro"},
    )

    await sender.send(event, Visitor(ip="203.0.113.9", user_agent=UA))

    (request,) = seen
    assert str(request.url) == "https://plausible.io/api/event"
    assert request.headers["user-agent"] == UA
    assert request.headers["x-forwarded-for"] == "203.0.113.9"
    assert json.loads(request.content) == {
        "name": "signup",
        "url": "https://app.example.com/signup",
        "domain": "app.example.com",
        "referrer": "https://google.com",
        "props": {"plan": "pro"},
    }


async def test_umami_format() -> None:
    settings = _settings(
        analytics_provider="umami",
        analytics_host="https://cloud.umami.is",
        analytics_site="0b5c1c36-0000-4000-8000-000000000000",
    )
    seen, transport = _capture()
    sender = UmamiSender(settings, transport=transport)

    await sender.send(AnalyticsEvent(path="/pricing"), Visitor(ip="203.0.113.9", user_agent=UA))
    await sender.send(
        AnalyticsEvent(name="signup", path="/signup", props={"plan": "pro"}),
        Visitor(ip="203.0.113.9", user_agent=UA),
    )

    view, custom = (json.loads(r.content) for r in seen)
    assert str(seen[0].url) == "https://cloud.umami.is/api/send"
    assert view == {
        "type": "event",
        "payload": {
            "website": "0b5c1c36-0000-4000-8000-000000000000",
            "hostname": "app.example.com",
            "url": "/pricing",
            "referrer": "",
        },
    }
    assert custom["payload"]["name"] == "signup"
    assert custom["payload"]["data"] == {"plan": "pro"}


async def test_provider_problems_never_raise() -> None:
    settings = _settings(
        analytics_provider="plausible", analytics_host="https://p.io", analytics_site="x"
    )

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    def rejects(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400)

    visitor = Visitor(ip="203.0.113.9", user_agent=UA)
    for handler in (down, rejects):
        sender = PlausibleSender(settings, transport=httpx.MockTransport(handler))
        await sender.send(AnalyticsEvent(path="/"), visitor)  # no exception


def test_build_sender_from_settings() -> None:
    assert build_analytics_sender(_settings()) is None
    plausible = _settings(
        analytics_provider="plausible", analytics_host="https://p.io", analytics_site="x"
    )
    umami = _settings(analytics_provider="umami", analytics_host="https://u.io", analytics_site="x")
    assert isinstance(build_analytics_sender(plausible), PlausibleSender)
    assert isinstance(build_analytics_sender(umami), UmamiSender)


def test_settings_need_host_and_site_when_on() -> None:
    with pytest.raises(ValueError, match="ANALYTICS_HOST and ANALYTICS_SITE"):
        _settings(analytics_provider="plausible")
    with pytest.raises(ValueError, match="must start with https"):
        _settings(analytics_provider="umami", analytics_host="cloud.umami.is", analytics_site="x")
