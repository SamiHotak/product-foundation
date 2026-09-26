"""Celery tasks.

`example_task` shows the pattern every long job uses: it is linked to a row in
the `jobs` table (base=JobTask), reports progress, retries temporary errors with
backoff, and returns a small JSON result.
"""

import smtplib
import time
from email.message import EmailMessage
from typing import Any

from app.core.config import get_settings
from app.core.logging import get_logger
from app.workers.celery_app import celery_app
from app.workers.jobs import JobFailedError, JobTask, TemporaryError, make_reporter

logger = get_logger(__name__)

__all__ = ["TemporaryError", "cleanup_auth", "example_task", "heartbeat", "send_email"]


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True,
    base=JobTask,
    name="app.workers.tasks.example_task",
    autoretry_for=(TemporaryError,),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
    max_retries=3,
)
def example_task(
    self: Any,
    job_id: str,
    steps: int = 5,
    fail: bool = False,
    delay_seconds: float = 1.0,
) -> dict[str, Any]:
    """Count through `steps`, reporting progress after each one.

    With `fail=True` it stops halfway with a user-facing error (to test the UI).
    """
    if not 1 <= steps <= 100:
        raise JobFailedError("Steps must be between 1 and 100.")
    report = make_reporter(job_id)
    logger.info("example_task_started", job_id=job_id, steps=steps, attempt=self.request.retries)
    for step in range(1, steps + 1):
        time.sleep(delay_seconds)
        if fail and step > steps // 2:
            raise JobFailedError(f"Stopped at step {step} of {steps} because you asked it to fail.")
        report.progress(round(step / steps * 100), f"Step {step} of {steps}")
    return {"steps": steps, "message": f"Finished {steps} steps."}


@celery_app.task(name="app.workers.tasks.heartbeat")  # type: ignore[untyped-decorator]
def heartbeat() -> str:
    """Scheduled by beat. Proves the scheduler and worker are alive (visible in logs)."""
    logger.info("heartbeat")
    return "ok"


@celery_app.task(  # type: ignore[untyped-decorator]
    name="app.workers.tasks.send_email",
    autoretry_for=(TemporaryError,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=6,
)
def send_email(to: str, subject: str, text: str, html: str | None = None) -> None:
    """Send one email over SMTP (Mailpit locally). Retries while the server is down."""
    settings = get_settings()
    msg = EmailMessage()
    msg["From"] = settings.email_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
            if settings.smtp_starttls:
                smtp.starttls()
            if settings.smtp_username and settings.smtp_password:
                smtp.login(settings.smtp_username, settings.smtp_password.get_secret_value())
            smtp.send_message(msg)
    except (OSError, smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError) as exc:
        logger.warning("email_send_retry", subject=subject, error=type(exc).__name__)
        raise TemporaryError("mail server not reachable") from exc
    # The address is personal data: log the subject only.
    logger.info("email_sent", subject=subject)


@celery_app.task(name="app.workers.tasks.cleanup_auth")  # type: ignore[untyped-decorator]
def cleanup_auth() -> dict[str, int]:
    """Nightly: delete expired sessions and old email tokens."""
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import delete, or_

    from app.db.session import sync_session
    from app.models.auth_token import AuthToken
    from app.models.session import UserSession

    now = datetime.now(UTC)
    with sync_session() as session:
        sessions = session.execute(delete(UserSession).where(UserSession.expires_at <= now))
        tokens = session.execute(
            delete(AuthToken).where(
                or_(
                    AuthToken.expires_at <= now - timedelta(days=7),
                    AuthToken.used_at <= now - timedelta(days=7),
                )
            )
        )
    counts = {
        "sessions": int(getattr(sessions, "rowcount", 0)),
        "tokens": int(getattr(tokens, "rowcount", 0)),
    }
    logger.info("cleanup_auth", **counts)
    return counts
