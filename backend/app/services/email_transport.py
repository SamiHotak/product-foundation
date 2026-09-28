"""How the worker hands an email to the mail provider (EMAIL_PROVIDER).

- smtp       any SMTP server. Locally Mailpit. Resend and Postmark also offer SMTP.
- resend     Resend's HTTP API (EMAIL_API_KEY = "re_...").
- postmark   Postmark's HTTP API (EMAIL_API_KEY = the server token).

A `TemporaryEmailError` makes the Celery task retry with backoff (provider down, rate
limit). A `PermanentEmailError` is logged and not retried (e.g. the sender domain is not
verified): retrying would never work, so we must fix the setup instead.
"""

import smtplib
from email.message import EmailMessage as MimeMessage
from typing import Any, Protocol

import httpx

from app.core.config import Settings
from app.services.email import EmailMessage

TIMEOUT = httpx.Timeout(15.0, connect=5.0)


class TemporaryEmailError(Exception):
    """Try again later."""


class PermanentEmailError(Exception):
    """Retrying will not help. The message is safe to log (no addresses, no keys)."""


class EmailTransport(Protocol):
    """Sends one email now (runs in the worker)."""

    def send(self, message: EmailMessage, *, idempotency_key: str | None = None) -> None:
        """Send or raise TemporaryEmailError / PermanentEmailError."""
        ...


class SmtpTransport:
    """SMTP (Mailpit locally, or a provider's SMTP relay)."""

    def __init__(self, settings: Settings) -> None:
        self._s = settings

    def send(self, message: EmailMessage, *, idempotency_key: str | None = None) -> None:
        """Send over SMTP."""
        msg = MimeMessage()
        msg["From"] = self._s.email_from
        msg["To"] = message.to
        msg["Subject"] = message.subject
        if self._s.email_reply_to:
            msg["Reply-To"] = self._s.email_reply_to
        msg.set_content(message.text)
        if message.html:
            msg.add_alternative(message.html, subtype="html")
        try:
            with smtplib.SMTP(self._s.smtp_host, self._s.smtp_port, timeout=10) as smtp:
                if self._s.smtp_starttls:
                    smtp.starttls()
                if self._s.smtp_username and self._s.smtp_password:
                    smtp.login(self._s.smtp_username, self._s.smtp_password.get_secret_value())
                smtp.send_message(msg)
        except smtplib.SMTPRecipientsRefused as exc:
            raise PermanentEmailError("recipient refused") from exc
        except smtplib.SMTPAuthenticationError as exc:
            raise PermanentEmailError("SMTP login failed: check SMTP_USERNAME/PASSWORD") from exc
        except (OSError, smtplib.SMTPException) as exc:
            raise TemporaryEmailError(type(exc).__name__) from exc


class _HttpTransport:
    """Shared HTTP handling: 429 / 5xx / network = try later, other 4xx = fix the setup."""

    url = ""

    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        assert settings.email_api_key is not None
        self._s = settings
        self._key = settings.email_api_key.get_secret_value()
        self._client = client or httpx.Client(timeout=TIMEOUT)

    def _post(self, headers: dict[str, str], body: dict[str, Any]) -> None:
        try:
            res = self._client.post(self.url, headers=headers, json=body)
        except httpx.HTTPError as exc:
            raise TemporaryEmailError(type(exc).__name__) from exc
        if res.status_code == 429 or res.status_code >= 500:
            raise TemporaryEmailError(f"HTTP {res.status_code}")
        if res.status_code >= 400:
            raise PermanentEmailError(f"HTTP {res.status_code}: {self._reason(res)}")

    @staticmethod
    def _reason(res: httpx.Response) -> str:
        try:
            data = res.json()
        except ValueError:
            return "no details"
        text = data.get("message") or data.get("Message") or data.get("name") or "no details"
        return str(text)[:200]


class ResendTransport(_HttpTransport):
    """https://resend.com/docs/api-reference/emails/send-email"""

    url = "https://api.resend.com/emails"

    def send(self, message: EmailMessage, *, idempotency_key: str | None = None) -> None:
        """Send with Resend."""
        headers = {"Authorization": f"Bearer {self._key}"}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key[:256]
        body: dict[str, Any] = {
            "from": self._s.email_from,
            "to": [message.to],
            "subject": message.subject,
            "text": message.text,
        }
        if message.html:
            body["html"] = message.html
        if self._s.email_reply_to:
            body["reply_to"] = self._s.email_reply_to
        self._post(headers, body)


class PostmarkTransport(_HttpTransport):
    """https://postmarkapp.com/developer/api/email-api"""

    url = "https://api.postmarkapp.com/email"

    def send(self, message: EmailMessage, *, idempotency_key: str | None = None) -> None:
        """Send with Postmark (transactional stream "outbound")."""
        headers = {"X-Postmark-Server-Token": self._key, "Accept": "application/json"}
        body: dict[str, Any] = {
            "From": self._s.email_from,
            "To": message.to,
            "Subject": message.subject,
            "TextBody": message.text,
            "MessageStream": "outbound",
        }
        if message.html:
            body["HtmlBody"] = message.html
        if self._s.email_reply_to:
            body["ReplyTo"] = self._s.email_reply_to
        self._post(headers, body)


def transport_for(settings: Settings) -> EmailTransport:
    """The transport for EMAIL_PROVIDER."""
    if settings.email_provider == "resend":
        return ResendTransport(settings)
    if settings.email_provider == "postmark":
        return PostmarkTransport(settings)
    return SmtpTransport(settings)
