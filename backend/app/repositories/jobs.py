"""Job persistence.

`JobRepository` (async) is used by the API. `SyncJobRepository` is used by Celery
workers and scripts. Phase 2 adds `organization_id` to every query here.
"""

import uuid
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models.job import Job, JobStatus, new_job_id


def _now() -> datetime:
    return datetime.now(UTC)


class JobStore(Protocol):
    """What the job service needs from storage (lets tests use an in-memory fake)."""

    async def create(self, *, kind: str, params: dict[str, Any]) -> Job:
        """Insert a queued job."""
        ...

    async def get(self, job_id: uuid.UUID) -> Job | None:
        """Return one job, or None."""
        ...

    async def list_recent(self, *, limit: int) -> list[Job]:
        """Newest jobs first."""
        ...

    async def mark_failed(self, job: Job, error: str) -> None:
        """Mark a job as failed (e.g. it could not be queued)."""
        ...

    async def commit(self) -> None:
        """Commit the current transaction."""
        ...


class JobRepository:
    """Async job queries for the API."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, *, kind: str, params: dict[str, Any]) -> Job:
        """Insert a queued job and return it with database defaults filled in."""
        job = Job(
            id=new_job_id(),
            kind=kind,
            status=JobStatus.QUEUED,
            progress=0,
            message="Waiting for a worker",
            params=params,
            attempts=0,
        )
        self._session.add(job)
        await self._session.flush()
        return job

    async def get(self, job_id: uuid.UUID) -> Job | None:
        """Return one job, or None."""
        return await self._session.get(Job, job_id, populate_existing=True)

    async def list_recent(self, *, limit: int) -> list[Job]:
        """Newest jobs first."""
        rows = await self._session.scalars(
            select(Job).order_by(Job.created_at.desc(), Job.id.desc()).limit(limit)
        )
        return list(rows)

    async def mark_failed(self, job: Job, error: str) -> None:
        """Mark a job as failed."""
        job.status = JobStatus.FAILED
        job.error = error
        job.message = None
        job.finished_at = _now()
        await self._session.flush()

    async def commit(self) -> None:
        """Commit the current transaction."""
        await self._session.commit()


class SyncJobRepository:
    """Sync job updates for Celery workers and scripts. Each method changes one row."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, *, kind: str, params: dict[str, Any]) -> Job:
        """Insert a queued job (used by scripts)."""
        job = Job(
            id=new_job_id(),
            kind=kind,
            status=JobStatus.QUEUED,
            progress=0,
            message="Waiting for a worker",
            params=params,
            attempts=0,
        )
        self._session.add(job)
        self._session.flush()
        return job

    def get(self, job_id: uuid.UUID) -> Job | None:
        """Return one job, or None."""
        return self._session.get(Job, job_id, populate_existing=True)

    def get_for_update(self, job_id: uuid.UUID) -> Job | None:
        """Return one job and lock its row until commit (safe concurrent updates)."""
        return self._session.get(Job, job_id, with_for_update=True, populate_existing=True)

    def mark_running(self, job: Job) -> None:
        """A worker picked the job up (again, after a retry or a crashed worker)."""
        job.status = JobStatus.RUNNING
        job.attempts += 1
        job.started_at = job.started_at or _now()
        job.message = "Started" if job.attempts == 1 else f"Started again (attempt {job.attempts})"
        job.error = None

    def set_progress(self, job: Job, progress: int, message: str | None) -> None:
        """Update progress (0-100) and the status text."""
        job.progress = max(0, min(100, progress))
        if message is not None:
            job.message = message[:500]

    def mark_retrying(self, job: Job, message: str) -> None:
        """A temporary error happened; the job waits for its next attempt."""
        job.status = JobStatus.QUEUED
        job.message = message[:500]

    def mark_done(self, job: Job, result: dict[str, Any] | None, message: str) -> None:
        """The job finished successfully."""
        job.status = JobStatus.DONE
        job.progress = 100
        job.result = result
        job.message = message[:500]
        job.error = None
        job.finished_at = _now()

    def mark_failed(self, job: Job, error: str) -> None:
        """The job failed for good (no retries left)."""
        job.status = JobStatus.FAILED
        job.error = error[:1000]
        job.message = None
        job.finished_at = _now()
