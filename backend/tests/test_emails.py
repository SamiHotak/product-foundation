"""Email templates (layout, escaping, plain text) and the provider transports."""

import json
import smtplib
from typing import Any, ClassVar

import httpx
import pytest
from pydantic import SecretStr

from app.core.config import Environment, Settings
from app.scripts.email_preview import all_templates
from app.services import email as emails
from app.services.email import EmailMessage
from app.services.email_transport import (
    PermanentEmailError,
    PostmarkTransport,
    ResendTransport,
    SmtpTransport,
    TemporaryEmailError,
    transport_for,
)

MSG = EmailMessage(to="a@example.com", subject="Hi", text="Hello", html="<p>Hello</p>")


def _settings(**changes: Any) -> Settings:
    return Settings(_env_file=None, environment=Environment.TEST, **changes)


# --- templates ----------------------------------------------------------------------------


def test_every_template_has_text_html_and_the_link() -> None:
    messages = all_templates("x@example.com", "Foundation", "https://app.example")
    assert len(messages) == 11
    for m in messages:
        assert m.text.strip() and m.html and m.subject
        assert m.html.startswith("<!doctype html>") and "</html>" in m.html
        assert "Foundation" in m.html  # the product name in the header
        assert "https://app.example" in m.html  # footer: which account this is about
        assert "{" not in m.subject and "{" not in m.text  # no unfilled placeholders
        links = [w for w in m.text.split() if w.startswith("https://")]
        assert links, f"no link in {m.subject!r}"
        for link in links:
            assert link in m.html  # the same link in both parts


def test_names_are_escaped_in_html() -> None:
    evil = '<script>alert("x")</script>'
    m = emails.invite_email(
        to="a@example.com",
        inviter_name=evil,
        organization_name="Acme & Co",
        role="admin",
        url="https://app.example/invite?token=abc&x=1",
        app_name="Foundation",
        days=7,
    )
    assert m.html is not None
    assert "<script>" not in m.html and "&lt;script&gt;" in m.html
    assert "Acme &amp; Co" in m.html
    assert 'href="https://app.example/invite?token=abc&amp;x=1"' in m.html
    assert "as an admin" in m.text and evil in m.text  # plain text is not HTML


def test_billing_emails_say_what_happens() -> None:
    common: dict[str, Any] = {
        "to": "o@example.com",
        "name": "Olga",
        "organization_name": "Acme",
        "billing_url": "https://app/settings/billing",
        "app_name": "Foundation",
    }
    trial = emails.plan_started_email(**common, plan_name="Pro", trial_end="1 October 2026")
    assert trial.subject == "Your Pro trial has started" and "1 October 2026" in trial.text
    paid = emails.plan_started_email(**common, plan_name="Pro", trial_end=None)
    assert paid.subject == "Welcome to Pro"
    failed = emails.payment_failed_email(**common, plan_name="Pro")
    assert "Update payment method: https://app/settings/billing" in failed.text
    ended = emails.plan_ended_email(**common, plan_name="Pro", free_plan_name="Free")
    assert ended.subject == "Acme is on the Free plan now" and "data is still there" in ended.text


def test_brand_color_and_footer_come_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import config

    settings = _settings(email_brand_color="#aa3300", email_footer_address="X Vision, Street 1")
    monkeypatch.setattr(config, "get_settings", lambda: settings)
    m = emails.password_reset_email(
        to="a@b.de", name="A", url="https://x/r?token=1", app_name="Foundation", minutes=60
    )
    assert m.html is not None and "#aa3300" in m.html and "X Vision, Street 1" in m.html


def test_bad_email_settings_are_refused() -> None:
    with pytest.raises(ValueError, match="EMAIL_API_KEY"):
        _settings(email_provider="resend")
    with pytest.raises(ValueError, match="EMAIL_BRAND_COLOR"):
        _settings(email_brand_color="blue")


# --- HTTP providers -----------------------------------------------------------------------


def _client(status: int, body: dict[str, Any], seen: list[httpx.Request]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json=body)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_resend_request_and_idempotency_key() -> None:
    seen: list[httpx.Request] = []
    settings = _settings(
        email_provider="resend",
        email_api_key=SecretStr("re_123"),
        email_reply_to="help@example.com",
    )
    ResendTransport(settings, _client(200, {"id": "e1"}, seen)).send(MSG, idempotency_key="task-1")
    [req] = seen
    assert str(req.url) == "https://api.resend.com/emails"
    assert req.headers["Authorization"] == "Bearer re_123"
    assert req.headers["Idempotency-Key"] == "task-1"
    body = json.loads(req.content)
    assert body["to"] == ["a@example.com"] and body["html"] == "<p>Hello</p>"
    assert body["reply_to"] == "help@example.com" and body["from"] == settings.email_from


def test_postmark_request() -> None:
    seen: list[httpx.Request] = []
    settings = _settings(email_provider="postmark", email_api_key=SecretStr("pm-token"))
    PostmarkTransport(settings, _client(200, {"ErrorCode": 0}, seen)).send(MSG)
    [req] = seen
    assert req.headers["X-Postmark-Server-Token"] == "pm-token"
    body = json.loads(req.content)
    assert body["MessageStream"] == "outbound" and body["HtmlBody"] == "<p>Hello</p>"


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (429, TemporaryEmailError),
        (500, TemporaryEmailError),
        (503, TemporaryEmailError),
        (401, PermanentEmailError),
        (422, PermanentEmailError),
    ],
)
def test_provider_errors_retry_only_when_it_can_help(status: int, error: type[Exception]) -> None:
    settings = _settings(email_provider="resend", email_api_key=SecretStr("re_123"))
    transport = ResendTransport(settings, _client(status, {"message": "domain not verified"}, []))
    with pytest.raises(error):
        transport.send(MSG)


def test_network_error_is_temporary() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    settings = _settings(email_provider="postmark", email_api_key=SecretStr("pm"))
    transport = PostmarkTransport(settings, httpx.Client(transport=httpx.MockTransport(boom)))
    with pytest.raises(TemporaryEmailError):
        transport.send(MSG)


def test_transport_for_provider() -> None:
    assert isinstance(transport_for(_settings()), SmtpTransport)
    key = SecretStr("k")
    assert isinstance(
        transport_for(_settings(email_provider="resend", email_api_key=key)), ResendTransport
    )
    assert isinstance(
        transport_for(_settings(email_provider="postmark", email_api_key=key)), PostmarkTransport
    )


# --- SMTP ---------------------------------------------------------------------------------


class FakeSmtp:
    sent: ClassVar[list[Any]] = []
    fail: ClassVar[Exception | None] = None

    def __init__(self, host: str, port: int, timeout: int) -> None:
        if FakeSmtp.fail:
            raise FakeSmtp.fail
        self.started_tls = False

    def __enter__(self) -> "FakeSmtp":
        return self

    def __exit__(self, *_: Any) -> None:
        return None

    def starttls(self) -> None:
        self.started_tls = True

    def login(self, user: str, password: str) -> None:
        if password == "wrong":
            raise smtplib.SMTPAuthenticationError(535, b"no")

    def send_message(self, msg: Any) -> None:
        FakeSmtp.sent.append(msg)


def test_smtp_sends_both_parts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(smtplib, "SMTP", FakeSmtp)
    FakeSmtp.sent, FakeSmtp.fail = [], None
    SmtpTransport(_settings(email_reply_to="help@example.com")).send(MSG)
    [msg] = FakeSmtp.sent
    assert msg["To"] == "a@example.com" and msg["Reply-To"] == "help@example.com"
    assert {p.get_content_type() for p in msg.iter_parts()} == {"text/plain", "text/html"}

    FakeSmtp.fail = ConnectionRefusedError()
    with pytest.raises(TemporaryEmailError):
        SmtpTransport(_settings()).send(MSG)
    FakeSmtp.fail = None
    with pytest.raises(PermanentEmailError):
        SmtpTransport(_settings(smtp_username="u", smtp_password=SecretStr("wrong"))).send(MSG)


# --- the worker task ----------------------------------------------------------------------


def test_send_email_task_retries_temporary_and_drops_permanent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.email_transport as transport_module
    from app.workers.tasks import send_email

    calls: list[str | None] = []

    class Flaky:
        def __init__(self, error: Exception | None) -> None:
            self.error = error

        def send(self, message: EmailMessage, *, idempotency_key: str | None = None) -> None:
            calls.append(idempotency_key)
            if self.error:
                raise self.error

    kwargs = {"to": "a@b.de", "subject": "S", "text": "T"}
    monkeypatch.setattr(transport_module, "transport_for", lambda s: Flaky(None))
    send_email.apply(kwargs=kwargs, task_id="task-42")
    assert calls == ["task-42"]  # the task id is the idempotency key

    monkeypatch.setattr(
        transport_module, "transport_for", lambda s: Flaky(PermanentEmailError("bad domain"))
    )
    result = send_email.apply(kwargs=kwargs)
    assert result.successful()  # logged, not retried

    monkeypatch.setattr(
        transport_module, "transport_for", lambda s: Flaky(TemporaryEmailError("503"))
    )
    result = send_email.apply(kwargs=kwargs)
    assert not result.successful()  # Celery retries (eager mode shows the retry as an error)
