"""Sentry: off by default, sends real bugs only, never sends personal data."""

from typing import Any

import pytest
import sentry_sdk
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sentry_sdk.transport import Transport

from app.core.config import Environment, Settings
from app.core.errors import NotFoundError
from app.core.sentry import init_sentry, scrub_event
from app.main import create_app


class _Capture(Transport):
    """Collects events instead of sending them."""

    def __init__(self, options: dict[str, Any]) -> None:
        super().__init__(options)
        self.events: list[dict[str, Any]] = []

    def capture_envelope(self, envelope: Any) -> None:
        event = envelope.get_event()
        if event is not None:
            self.events.append(event)


def _settings(**changes: object) -> Settings:
    values: dict[str, object] = {"environment": Environment.TEST, **changes}
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _reset_sentry() -> Any:
    yield
    sentry_sdk.get_client().close()
    sentry_sdk.init()  # back to "off"


def test_off_without_dsn() -> None:
    assert init_sentry(_settings(), component="api") is False
    assert not sentry_sdk.get_client().is_active()


def test_dsn_must_be_https() -> None:
    with pytest.raises(ValueError, match="https"):
        _settings(sentry_dsn="http://key@example.com/1")


def test_scrub_removes_personal_data() -> None:
    event: dict[str, Any] = {
        "request": {
            "data": {"password": "hunter2"},
            "cookies": {"session": "abc"},
            "query_string": "token=abc",
            "headers": {"Cookie": "session=abc", "Authorization": "Bearer x", "Accept": "*/*"},
        },
        "user": {"email": "a@b.c", "ip_address": "1.2.3.4"},
    }
    out = scrub_event(event, {})
    assert out is not None
    assert out["request"] == {"headers": {"Accept": "*/*"}}
    assert "user" not in out


def test_scrub_removes_emails_and_ips_inside_texts() -> None:
    event: dict[str, Any] = {
        "exception": {
            "values": [
                {
                    "type": "UniqueViolation",
                    "value": "Key (email)=(ann.lee+x@example.com) already exists; client 10.1.2.3",
                }
            ]
        },
        "breadcrumbs": {
            "values": [{"message": "mail to bob@example.org failed", "data": {"n": 3}}]
        },
        "logentry": {"message": "sending to %s", "params": ["carol@example.de"]},
    }
    out = scrub_event(event, {})
    assert out is not None
    text = str(out)
    assert "@example" not in text
    assert "10.1.2.3" not in text
    assert "[email]" in text and "[ip]" in text
    assert out["breadcrumbs"]["values"][0]["data"] == {"n": 3}


def _start(app_settings: Settings) -> _Capture:
    capture = _Capture({})
    assert init_sentry(app_settings, component="api", transport=capture)
    return capture


async def test_real_bugs_are_reported_but_expected_errors_are_not() -> None:
    settings = _settings(sentry_dsn="https://key@o1.ingest.sentry.io/1", sentry_release="sha-abc")
    app: FastAPI = create_app(settings)
    capture = _start(settings)  # create_app started Sentry too; swap in the collecting transport

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("real bug")

    @app.get("/missing")
    async def missing() -> None:
        raise NotFoundError("nope")

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/missing")).status_code == 404
        assert (await client.get("/boom", headers={"Cookie": "session=secret"})).status_code == 500
    sentry_sdk.flush()

    messages = [
        (e.get("exception", {}).get("values") or [{}])[0].get("value") for e in capture.events
    ]
    assert "real bug" in messages
    assert "nope" not in messages
    boom_event = next(e for e in capture.events if "real bug" in str(e))
    assert "session=secret" not in str(boom_event)
    assert boom_event["release"] == "sha-abc"
