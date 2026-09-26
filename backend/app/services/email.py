"""Transactional emails: the messages and how they are handed to the worker.

The API never talks to the mail server directly. It queues a Celery task
(`app.workers.tasks.send_email`), which retries if the server is down.
Locally the mail server is Mailpit (http://localhost:8025). Phase 4A adds a provider
(Resend/Postmark) and proper HTML templates.
"""

import asyncio
from dataclasses import asdict, dataclass
from html import escape
from typing import Protocol

from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class EmailMessage:
    """One email. `html` is optional; `text` is always sent."""

    to: str
    subject: str
    text: str
    html: str | None = None


class EmailSender(Protocol):
    """Sends (or queues) an email. Tests use a fake that records messages."""

    async def send(self, message: EmailMessage) -> None:
        """Send or queue the message. Must not raise for delivery problems."""
        ...


class CeleryEmailSender:
    """Queues the email for the worker. A queue outage is logged, never shown to users."""

    async def send(self, message: EmailMessage) -> None:
        """Queue the send_email task."""
        from app.workers.celery_app import celery_app

        def _publish() -> None:
            celery_app.send_task(
                "app.workers.tasks.send_email",
                kwargs=asdict(message),
                ignore_result=True,
                retry=True,
                retry_policy={"max_retries": 2, "interval_start": 0, "interval_step": 0.2},
            )

        try:
            await asyncio.to_thread(_publish)
        except Exception as exc:
            logger.error("email_queue_failed", subject=message.subject, error=type(exc).__name__)


def _html(paragraphs: list[str], button: tuple[str, str] | None = None) -> str:
    body = "".join(f"<p>{p}</p>" for p in paragraphs)
    if button:
        label, url = button
        body += (
            f'<p><a href="{escape(url)}" style="display:inline-block;padding:10px 16px;'
            f"background:#244ba6;color:#fff;border-radius:6px;text-decoration:none;"
            f'font-weight:600">{escape(label)}</a></p>'
            f'<p style="color:#586277;font-size:13px">Or open this link: {escape(url)}</p>'
        )
    return (
        f'<div style="font-family:system-ui,sans-serif;font-size:15px;color:#1b2233">{body}</div>'
    )


def verification_email(*, to: str, name: str, url: str, app_name: str, hours: int) -> EmailMessage:
    """Sent after sign-up (and on "resend")."""
    greeting = f"Hi {name},"
    lines = [
        f"please confirm your email address to finish creating your {app_name} account.",
        f"The link works for {hours} hours. If you did not sign up, ignore this email.",
    ]
    return EmailMessage(
        to=to,
        subject=f"Confirm your email for {app_name}",
        text=f"{greeting}\n\n{lines[0]}\n\n{url}\n\n{lines[1]}\n",
        html=_html([escape(greeting), escape(lines[0])], ("Confirm email", url))
        + _html([escape(lines[1])]),
    )


def account_exists_email(
    *, to: str, name: str, login_url: str, reset_url: str, app_name: str
) -> EmailMessage:
    """Someone tried to sign up with an email that already has an account.

    The sign-up page shows the same "check your email" message either way, so nobody can
    find out which emails are registered.
    """
    text = (
        f"Hi {name},\n\nsomeone (probably you) tried to create a new {app_name} account with "
        f"this email address, but you already have one.\n\nSign in: {login_url}\n"
        f"Forgot your password? {reset_url}\n\nIf this was not you, you can ignore this email.\n"
    )
    return EmailMessage(
        to=to,
        subject=f"You already have a {app_name} account",
        text=text,
        html=_html(
            [
                escape(f"Hi {name},"),
                escape(
                    f"someone (probably you) tried to create a new {app_name} account "
                    "with this email address, but you already have one."
                ),
            ],
            ("Sign in", login_url),
        )
        + _html([f'Forgot your password? <a href="{escape(reset_url)}">Reset it</a>.']),
    )


def password_reset_email(
    *, to: str, name: str, url: str, app_name: str, minutes: int
) -> EmailMessage:
    """Sent when someone asks to reset the password."""
    lines = [
        f"we got a request to reset the password of your {app_name} account.",
        f"The link works for {minutes} minutes and only once. If you did not ask for this, "
        "ignore this email: your password stays the same.",
    ]
    return EmailMessage(
        to=to,
        subject=f"Reset your {app_name} password",
        text=f"Hi {name},\n\n{lines[0]}\n\n{url}\n\n{lines[1]}\n",
        html=_html([escape(f"Hi {name},"), escape(lines[0])], ("Choose a new password", url))
        + _html([escape(lines[1])]),
    )


def invite_email(
    *,
    to: str,
    inviter_name: str,
    organization_name: str,
    role: str,
    url: str,
    app_name: str,
    days: int,
) -> EmailMessage:
    """Someone invited this address to join a workspace."""
    lines = [
        f"{inviter_name} invited you to join the workspace “{organization_name}” on {app_name} "
        f"as {'an' if role == 'admin' else 'a'} {role}.",
        f"The link works for {days} days. If you don't know {inviter_name}, ignore this email.",
    ]
    return EmailMessage(
        to=to,
        subject=f"{inviter_name} invited you to {organization_name} on {app_name}",
        text=f"Hi,\n\n{lines[0]}\n\nAccept the invite: {url}\n\n{lines[1]}\n",
        html=_html(["Hi,", escape(lines[0])], ("Accept invite", url)) + _html([escape(lines[1])]),
    )


def account_deletion_email(
    *, to: str, name: str, when: str, settings_url: str, app_name: str
) -> EmailMessage:
    """Confirms that the account will be deleted, and how to stop it."""
    lines = [
        f"your {app_name} account and all its personal data will be deleted on {when}.",
        "Changed your mind? Sign in before then and cancel it under Settings → Privacy.",
        "If you did not ask for this, sign in now, cancel it and change your password.",
    ]
    return EmailMessage(
        to=to,
        subject=f"Your {app_name} account will be deleted on {when}",
        text=f"Hi {name},\n\n{lines[0]}\n\n{lines[1]}\n{settings_url}\n\n{lines[2]}\n",
        html=_html(
            [escape(f"Hi {name},"), escape(lines[0]), escape(lines[1])],
            ("Open privacy settings", settings_url),
        )
        + _html([escape(lines[2])]),
    )


def workspace_deletion_email(
    *, to: str, name: str, organization_name: str, when: str, settings_url: str, app_name: str
) -> EmailMessage:
    """Tells the owner the workspace will be deleted, and how to stop it."""
    lines = [
        f"the workspace “{organization_name}” and all its data will be deleted on {when}.",
        "Changed your mind? Cancel it before then under Settings → Privacy.",
    ]
    return EmailMessage(
        to=to,
        subject=f"“{organization_name}” will be deleted on {when}",
        text=f"Hi {name},\n\n{lines[0]}\n\n{lines[1]}\n{settings_url}\n",
        html=_html(
            [escape(f"Hi {name},"), escape(lines[0]), escape(lines[1])],
            ("Open privacy settings", settings_url),
        ),
    )
