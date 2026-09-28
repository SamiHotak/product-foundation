"""Send one of every email template, so you can check how they look.

    make email-preview          then open http://localhost:8025 (Mailpit)

Uses EMAIL_PROVIDER like the app. Locally that is Mailpit, so nothing leaves your laptop.
With a real provider configured, pass --to with YOUR address.
"""

import argparse
import sys

from app.core.config import get_settings
from app.services import email as emails
from app.services.email import EmailMessage
from app.services.email_transport import transport_for


def all_templates(to: str, app_name: str, app_url: str) -> list[EmailMessage]:
    """Every template with sample data."""
    link = f"{app_url}/example?token=preview"
    billing = f"{app_url}/settings/billing"
    person = {"to": to, "name": "Ezat"}
    org = {"organization_name": "Ezat's workspace", "billing_url": billing, "app_name": app_name}
    return [
        emails.verification_email(**person, url=link, app_name=app_name, hours=48),
        emails.account_exists_email(
            **person, login_url=f"{app_url}/login", reset_url=link, app_name=app_name
        ),
        emails.password_reset_email(**person, url=link, app_name=app_name, minutes=60),
        emails.invite_email(
            to=to,
            inviter_name="Mia",
            organization_name="Ezat's workspace",
            role="admin",
            url=link,
            app_name=app_name,
            days=7,
        ),
        emails.account_deletion_email(
            **person, when="12 October 2026", settings_url=link, app_name=app_name
        ),
        emails.workspace_deletion_email(
            **person,
            organization_name="Ezat's workspace",
            when="12 October 2026",
            settings_url=link,
            app_name=app_name,
        ),
        emails.plan_started_email(**person, **org, plan_name="Pro", trial_end="12 October 2026"),
        emails.plan_started_email(**person, **org, plan_name="Pro", trial_end=None),
        emails.trial_ending_email(**person, **org, plan_name="Pro", trial_end="12 October 2026"),
        emails.payment_failed_email(**person, **org, plan_name="Pro"),
        emails.plan_ended_email(**person, **org, plan_name="Pro", free_plan_name="Free"),
    ]


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(description="Send every email template once.")
    parser.add_argument("--to", default="preview@example.com")
    args = parser.parse_args(argv)
    settings = get_settings()
    transport = transport_for(settings)
    messages = all_templates(args.to, settings.app_name, settings.app_url)
    for message in messages:
        transport.send(message)
    print(f"Sent {len(messages)} emails to {args.to} via {settings.email_provider}.")
    if settings.email_provider == "smtp" and settings.smtp_host in {"mailpit", "localhost"}:
        print("Open http://localhost:8025 to see them.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
