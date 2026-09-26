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

__all__ = [
    "TemporaryError",
    "cleanup_auth",
    "cleanup_data",
    "data_export",
    "example_task",
    "heartbeat",
    "purge_deleted",
    "send_email",
]


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


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True,
    base=JobTask,
    name="app.workers.tasks.data_export",
    autoretry_for=(TemporaryError,),
    retry_backoff=True,
    max_retries=3,
)
def data_export(self: Any, job_id: str, export_id: str) -> dict[str, Any]:
    """Build a GDPR export ZIP and store it. The UI then shows a download link."""
    import uuid

    from app.db.session import sync_session
    from app.repositories.exports import SyncExportReader
    from app.services.export_builder import build_zip

    report = make_reporter(job_id)
    report.progress(5, "Collecting your data")
    with sync_session() as session:
        reader = SyncExportReader(session)
        export = reader.get_export(uuid.UUID(export_id))
        if export is None:
            raise JobFailedError("This export was deleted before it was ready.")
        content = build_zip(
            reader,
            export,
            app_name=get_settings().app_name,
            progress=lambda pct, msg: report.progress(pct, msg),
        )
        reader.save_content(export, content)
        filename = export.filename
    size_kb = max(1, round(len(content) / 1024))
    return {
        "export_id": export_id,
        "size_bytes": len(content),
        "message": f"Your export is ready ({filename}, {size_kb} KB).",
    }


@celery_app.task(name="app.workers.tasks.purge_deleted")  # type: ignore[untyped-decorator]
def purge_deleted() -> dict[str, int]:
    """Nightly: delete accounts and workspaces whose deletion date has passed (GDPR)."""
    from datetime import UTC, datetime

    from app.db.session import sync_session
    from app.services.purge import purge_due

    counts = purge_due(sync_session, datetime.now(UTC))
    logger.info("purge_deleted", **counts)
    return counts


@celery_app.task(name="app.workers.tasks.cleanup_data")  # type: ignore[untyped-decorator]
def cleanup_data() -> dict[str, int]:
    """Nightly: remove expired export files and audit events past their retention."""
    from datetime import UTC, datetime

    from app.db.session import sync_session
    from app.services.purge import cleanup

    counts = cleanup(
        sync_session,
        datetime.now(UTC),
        audit_retention_days=get_settings().audit_retention_days,
    )
    logger.info("cleanup_data", **counts)
    return counts
