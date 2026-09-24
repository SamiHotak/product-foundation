"""Link Celery tasks to rows in the `jobs` table.

Use `base=JobTask` on a task and give it a `job_id` keyword argument. Then:
- before it starts        -> status "running", attempts + 1
- `report.progress(...)`  -> progress % and a short message (call it from the task)
- temporary error + retry -> status "queued" with a "retrying" message
- success                 -> status "done", progress 100, the returned dict as result
- final failure           -> status "failed" with a SAFE error text

Only `JobFailedError` messages are shown to users. Any other exception shows a
generic text; the full error is in the worker logs (search for the job id).
"""

import uuid
from typing import Any, Protocol

from celery import Task

from app.core.logging import get_logger
from app.db.session import sync_session
from app.repositories.jobs import SyncJobRepository

logger = get_logger(__name__)


class TemporaryError(Exception):
    """An error worth retrying (network blip, rate limit, ...)."""


class JobFailedError(Exception):
    """A failure with a message that is safe to show to the user."""


def safe_error_message(exc: BaseException, job_id: str) -> str:
    """User-facing text for a failure. Never leaks internal details."""
    if isinstance(exc, JobFailedError):
        return str(exc)[:1000]
    return f"Something went wrong while running this job. Reference: {job_id}"


class JobReporter(Protocol):
    """Writes a job's status. Tests replace it with an in-memory fake."""

    def started(self) -> None:
        """A worker picked up the job."""
        ...

    def progress(self, percent: int, message: str | None = None) -> None:
        """Report progress (0-100)."""
        ...

    def retrying(self, message: str) -> None:
        """A temporary error happened; the job will run again."""
        ...

    def succeeded(self, result: dict[str, Any] | None) -> None:
        """The job finished."""
        ...

    def failed(self, error: str) -> None:
        """The job failed for good."""
        ...


class DbJobReporter:
    """Writes job status to Postgres. Each call is its own short transaction."""

    def __init__(self, job_id: str) -> None:
        self.job_id = job_id
        self._uuid = uuid.UUID(job_id)

    def started(self) -> None:
        """Mark the job running."""
        with sync_session() as session:
            repo = SyncJobRepository(session)
            job = repo.get_for_update(self._uuid)
            if job is None:
                logger.warning("job_row_missing", job_id=self.job_id)
                return
            repo.mark_running(job)

    def progress(self, percent: int, message: str | None = None) -> None:
        """Update progress unless the job already finished."""
        with sync_session() as session:
            repo = SyncJobRepository(session)
            job = repo.get_for_update(self._uuid)
            if job is None or job.status.is_finished:
                return
            repo.set_progress(job, percent, message)

    def retrying(self, message: str) -> None:
        """Mark the job waiting for its next attempt."""
        with sync_session() as session:
            repo = SyncJobRepository(session)
            job = repo.get_for_update(self._uuid)
            if job is not None:
                repo.mark_retrying(job, message)

    def succeeded(self, result: dict[str, Any] | None) -> None:
        """Mark the job done."""
        message = "Done"
        if result and isinstance(result.get("message"), str):
            message = result["message"]
        with sync_session() as session:
            repo = SyncJobRepository(session)
            job = repo.get_for_update(self._uuid)
            if job is not None:
                repo.mark_done(job, result, message)

    def failed(self, error: str) -> None:
        """Mark the job failed."""
        with sync_session() as session:
            repo = SyncJobRepository(session)
            job = repo.get_for_update(self._uuid)
            if job is not None:
                repo.mark_failed(job, error)


def make_reporter(job_id: str) -> JobReporter:
    """Build the reporter for a job (tests monkeypatch this function)."""
    return DbJobReporter(job_id)


def _job_id(kwargs: dict[str, Any] | None) -> str | None:
    value = (kwargs or {}).get("job_id")
    return value if isinstance(value, str) else None


class JobTask(Task):  # type: ignore[misc]  # Celery has no type hints
    """Celery base class that keeps the job row in sync with the task's life cycle."""

    abstract = True

    def before_start(self, task_id: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
        """Runs in the worker right before the task body (also on every retry)."""
        if job_id := _job_id(kwargs):
            make_reporter(job_id).started()

    def on_success(
        self, retval: Any, task_id: str, args: tuple[Any, ...], kwargs: dict[str, Any]
    ) -> None:
        """Task returned normally."""
        if job_id := _job_id(kwargs):
            make_reporter(job_id).succeeded(retval if isinstance(retval, dict) else None)
            logger.info("job_done", job_id=job_id, task=self.name)

    def on_retry(
        self,
        exc: BaseException,
        task_id: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        einfo: Any,
    ) -> None:
        """A temporary error happened and a retry is scheduled."""
        if job_id := _job_id(kwargs):
            attempt = self.request.retries + 2  # retries counts previous retries
            total = (self.max_retries or 0) + 1
            make_reporter(job_id).retrying(
                f"A temporary problem happened. Retrying (attempt {attempt} of {total})."
            )
            logger.warning(
                "job_retrying", job_id=job_id, task=self.name, error_type=type(exc).__name__
            )

    def on_failure(
        self,
        exc: BaseException,
        task_id: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        einfo: Any,
    ) -> None:
        """Final failure: no retries left, or a non-retryable error."""
        if job_id := _job_id(kwargs):
            make_reporter(job_id).failed(safe_error_message(exc, job_id))
            logger.error(
                "job_failed",
                job_id=job_id,
                task=self.name,
                error_type=type(exc).__name__,
                exc_info=exc,
            )
