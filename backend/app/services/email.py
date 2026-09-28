"""Transactional emails: the templates, and how they are handed to the worker.

The API never talks to the mail provider directly. It queues a Celery task
(`app.workers.tasks.send_email`), which sends through the provider in EMAIL_PROVIDER
(app/services/email_transport.py) and retries while the provider is down.
Locally everything lands in Mailpit (http://localhost:8025).

Every email has a plain-text part (always) and an HTML part built with `_render()`:
one simple, table-based layout that works in Gmail, Outlook and Apple Mail.
See all templates at once:  make email-preview   (then open Mailpit).
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


# --- layout -------------------------------------------------------------------------------


class Html(str):
    """Text that is already safe HTML (e.g. contains a link we built). Everything else is
    escaped by `_render()`."""


@dataclass(frozen=True)
class Brand:
    """How emails look and who sends them (from settings)."""

    app_name: str
    app_url: str
    color: str = "#244ba6"
    footer_address: str = ""


def _brand(app_name: str) -> Brand:
    from app.core.config import get_settings

    s = get_settings()
    return Brand(
        app_name=app_name,
        app_url=s.app_url,
        color=s.email_brand_color,
        footer_address=s.email_footer_address,
    )


def _p(value: str) -> str:
    return value if isinstance(value, Html) else escape(value)


def _render(
    brand: Brand,
    *,
    preheader: str,
    heading: str,
    paragraphs: list[str],
    button: tuple[str, str] | None = None,
    after: list[str] | None = None,
) -> str:
    """The HTML part: heading, text, one button (with the plain link under it), footer."""
    font = "-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
    body = "".join(
        f'<p style="margin:0 0 16px;font-size:15px;line-height:24px;color:#1b2233">{_p(p)}</p>'
        for p in paragraphs
    )
    if button:
        label, url = button
        body += (
            '<table role="presentation" cellspacing="0" cellpadding="0" border="0" '
            'style="margin:8px 0 16px"><tr>'
            f'<td style="border-radius:6px;background:{brand.color}">'
            f'<a href="{escape(url)}" style="display:inline-block;padding:11px 18px;'
            f"font-family:{font};font-size:15px;font-weight:600;color:#ffffff;"
            f'text-decoration:none;border-radius:6px">{escape(label)}</a></td></tr></table>'
            '<p style="margin:0 0 16px;font-size:13px;line-height:20px;color:#586277">'
            f'Button not working? Open this link:<br><a href="{escape(url)}" '
            f'style="color:{brand.color};word-break:break-all">{escape(url)}</a></p>'
        )
    for p in after or []:
        body += (
            f'<p style="margin:0 0 12px;font-size:13px;line-height:20px;color:#586277">{_p(p)}</p>'
        )
    footer = escape(brand.app_name)
    if brand.footer_address:
        footer += f" · {escape(brand.footer_address)}"
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="color-scheme" content="light"><meta name="supported-color-schemes" '
        f'content="light"><title>{escape(heading)}</title></head>'
        f'<body style="margin:0;padding:0;background:#f3f5f8;font-family:{font}">'
        '<div style="display:none;max-height:0;overflow:hidden;opacity:0">'
        f"{escape(preheader)}</div>"
        '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" '
        'style="background:#f3f5f8"><tr><td align="center" style="padding:32px 16px">'
        '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" '
        'style="max-width:560px">'
        '<tr><td style="padding:0 4px 16px;font-size:15px;font-weight:700;color:#1b2233">'
        f"{escape(brand.app_name)}</td></tr>"
        '<tr><td style="background:#ffffff;border:1px solid #e3e7ee;border-radius:10px;'
        'padding:28px 28px 12px">'
        '<h1 style="margin:0 0 16px;font-size:20px;line-height:28px;color:#1b2233">'
        f"{escape(heading)}</h1>{body}</td></tr>"
        '<tr><td style="padding:16px 4px;font-size:12px;line-height:18px;color:#7a8499">'
        f"{footer}<br>This is a service email about your account at "
        f'<a href="{escape(brand.app_url)}" style="color:#7a8499">'
        f"{escape(brand.app_url)}</a>.</td></tr>"
        "</table></td></tr></table></body></html>"
    )


def _text(greeting: str, lines: list[str], link: tuple[str, str] | None, after: list[str]) -> str:
    parts = [greeting, *lines]
    if link:
        parts.append(f"{link[0]}: {link[1]}")
    parts.extend(after)
    return "\n\n".join(p for p in parts if p) + "\n"


def _email(
    *,
    to: str,
    subject: str,
    app_name: str,
    greeting: str,
    lines: list[str],
    button: tuple[str, str] | None = None,
    after: list[str] | None = None,
    preheader: str | None = None,
) -> EmailMessage:
    after = after or []
    return EmailMessage(
        to=to,
        subject=subject,
        text=_text(greeting, [str(line) for line in lines], button, [str(a) for a in after]),
        html=_render(
            _brand(app_name),
            preheader=preheader or (lines[0] if lines else subject),
            heading=subject,
            paragraphs=[greeting, *lines],
            button=button,
            after=after,
        ),
    )


# --- account ------------------------------------------------------------------------------


def verification_email(*, to: str, name: str, url: str, app_name: str, hours: int) -> EmailMessage:
    """Sent after sign-up (and on "resend")."""
    return _email(
        to=to,
        subject=f"Confirm your email for {app_name}",
        app_name=app_name,
        greeting=f"Hi {name},",
        lines=[f"please confirm your email address to finish creating your {app_name} account."],
        button=("Confirm email", url),
        after=[f"The link works for {hours} hours. If you did not sign up, ignore this email."],
    )


def account_exists_email(
    *, to: str, name: str, login_url: str, reset_url: str, app_name: str
) -> EmailMessage:
    """Someone tried to sign up with an email that already has an account.

    The sign-up page shows the same "check your email" message either way, so nobody can
    find out which emails are registered.
    """
    msg = _email(
        to=to,
        subject=f"You already have a {app_name} account",
        app_name=app_name,
        greeting=f"Hi {name},",
        lines=[
            f"someone (probably you) tried to create a new {app_name} account with this email "
            "address, but you already have one."
        ],
        button=("Sign in", login_url),
        after=[
            Html(f'Forgot your password? <a href="{escape(reset_url)}">Reset it</a>.'),
            "If this was not you, you can ignore this email.",
        ],
    )
    text = (
        f"Hi {name},\n\nsomeone (probably you) tried to create a new {app_name} account with "
        f"this email address, but you already have one.\n\nSign in: {login_url}\n"
        f"Forgot your password? {reset_url}\n\nIf this was not you, you can ignore this email.\n"
    )
    return EmailMessage(to=msg.to, subject=msg.subject, text=text, html=msg.html)


def password_reset_email(
    *, to: str, name: str, url: str, app_name: str, minutes: int
) -> EmailMessage:
    """Sent when someone asks to reset the password."""
    return _email(
        to=to,
        subject=f"Reset your {app_name} password",
        app_name=app_name,
        greeting=f"Hi {name},",
        lines=[f"we got a request to reset the password of your {app_name} account."],
        button=("Choose a new password", url),
        after=[
            f"The link works for {minutes} minutes and only once. If you did not ask for this, "
            "ignore this email: your password stays the same."
        ],
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
    return _email(
        to=to,
        subject=f"{inviter_name} invited you to {organization_name} on {app_name}",
        app_name=app_name,
        greeting="Hi,",
        lines=[
            f"{inviter_name} invited you to join the workspace “{organization_name}” on "
            f"{app_name} as {'an' if role == 'admin' else 'a'} {role}."
        ],
        button=("Accept invite", url),
        after=[f"The link works for {days} days. If you don't know {inviter_name}, ignore this."],
    )


def account_deletion_email(
    *, to: str, name: str, when: str, settings_url: str, app_name: str
) -> EmailMessage:
    """Confirms that the account will be deleted, and how to stop it."""
    return _email(
        to=to,
        subject=f"Your {app_name} account will be deleted on {when}",
        app_name=app_name,
        greeting=f"Hi {name},",
        lines=[
            f"your {app_name} account and all its personal data will be deleted on {when}.",
            "Changed your mind? Sign in before then and cancel it under Settings → Privacy.",
        ],
        button=("Open privacy settings", settings_url),
        after=["If you did not ask for this, sign in now, cancel it and change your password."],
    )


def workspace_deletion_email(
    *, to: str, name: str, organization_name: str, when: str, settings_url: str, app_name: str
) -> EmailMessage:
    """Tells the owner the workspace will be deleted, and how to stop it."""
    return _email(
        to=to,
        subject=f"“{organization_name}” will be deleted on {when}",
        app_name=app_name,
        greeting=f"Hi {name},",
        lines=[
            f"the workspace “{organization_name}” and all its data will be deleted on {when}. "
            "A paid plan of this workspace ends then too (no further charges).",
            "Changed your mind? Cancel it before then under Settings → Privacy.",
        ],
        button=("Open privacy settings", settings_url),
    )


# --- billing ------------------------------------------------------------------------------


def plan_started_email(
    *,
    to: str,
    name: str,
    organization_name: str,
    plan_name: str,
    trial_end: str | None,
    billing_url: str,
    app_name: str,
) -> EmailMessage:
    """A workspace moved to a paid plan (or started its free trial)."""
    if trial_end:
        subject = f"Your {plan_name} trial has started"
        lines = [
            f"“{organization_name}” is now on the {plan_name} plan. Your free trial runs until "
            f"{trial_end}. We charge the card you added on that day, unless you cancel before.",
        ]
    else:
        subject = f"Welcome to {plan_name}"
        lines = [f"“{organization_name}” is now on the {plan_name} plan. Thank you!"]
    lines.append("Stripe emails your receipts. Invoices are also under Settings → Billing.")
    return _email(
        to=to,
        subject=subject,
        app_name=app_name,
        greeting=f"Hi {name},",
        lines=lines,
        button=("Open billing settings", billing_url),
    )


def trial_ending_email(
    *,
    to: str,
    name: str,
    organization_name: str,
    plan_name: str,
    trial_end: str,
    billing_url: str,
    app_name: str,
) -> EmailMessage:
    """Stripe tells us 3 days before a trial ends."""
    return _email(
        to=to,
        subject=f"Your {plan_name} trial ends on {trial_end}",
        app_name=app_name,
        greeting=f"Hi {name},",
        lines=[
            f"the free trial of “{organization_name}” ends on {trial_end}. After that, the "
            f"{plan_name} plan continues and your card is charged.",
            "Nothing to do if you want to keep it. To stop, cancel before that day.",
        ],
        button=("Manage billing", billing_url),
    )


def payment_failed_email(
    *,
    to: str,
    name: str,
    organization_name: str,
    plan_name: str,
    billing_url: str,
    app_name: str,
) -> EmailMessage:
    """A payment did not go through. Stripe tries again over the next days."""
    return _email(
        to=to,
        subject=f"Payment failed for {organization_name}",
        app_name=app_name,
        greeting=f"Hi {name},",
        lines=[
            f"we could not charge your card for the {plan_name} plan of “{organization_name}”.",
            "We will try again over the next days. Please check or update your payment method, "
            "so the workspace keeps its plan.",
        ],
        button=("Update payment method", billing_url),
    )


def plan_ended_email(
    *,
    to: str,
    name: str,
    organization_name: str,
    plan_name: str,
    free_plan_name: str,
    billing_url: str,
    app_name: str,
) -> EmailMessage:
    """The paid plan ended (cancelled, or payments failed). The workspace is on free now."""
    return _email(
        to=to,
        subject=f"{organization_name} is on the {free_plan_name} plan now",
        app_name=app_name,
        greeting=f"Hi {name},",
        lines=[
            f"the {plan_name} plan of “{organization_name}” has ended. Your data is still there; "
            f"the limits of the {free_plan_name} plan apply now.",
            "You can choose a plan again at any time.",
        ],
        button=("See plans", billing_url),
    )
