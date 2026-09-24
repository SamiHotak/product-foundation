"""In-memory fakes for jobs (no Postgres, no Redis)."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from app.models.job import Job, JobStatus


class FakeJobStore:
    """Implements app.repositories.jobs.JobStore in memory."""

    def __init__(self) -> None:
        self.jobs: dict[uuid.UUID, Job] = {}
        self.commits = 0

    async def create(self, *, kind: str, params: dict[str, Any]) -> Job:
        # Strictly increasing timestamps, so ordering is deterministic.
        now = datetime.now(UTC) + timedelta(microseconds=len(self.jobs))
        job = Job(
            id=uuid.uuid4(),
            kind=kind,
            status=JobStatus.QUEUED,
            progress=0,
            message="Waiting for a worker",
            params=params,
            result=None,
            error=None,
            attempts=0,
            created_at=now,
            updated_at=now,
            started_at=None,
            finished_at=None,
        )
        self.jobs[job.id] = job
        return job

    async def get(self, job_id: uuid.UUID) -> Job | None:
        return self.jobs.get(job_id)

    async def list_recent(self, *, limit: int) -> list[Job]:
        return sorted(self.jobs.values(), key=lambda j: j.created_at, reverse=True)[:limit]

    async def mark_failed(self, job: Job, error: str) -> None:
        job.status = JobStatus.FAILED
        job.error = error
        job.finished_at = datetime.now(UTC)

    async def commit(self) -> None:
        self.commits += 1


class FakeDispatcher:
    """Records dispatched jobs; can simulate a queue outage."""

    def __init__(self, *, fail: bool = False) -> None:
        self.sent: list[Job] = []
        self.fail = fail
        self.commits_seen: list[int] = []
        self.store: FakeJobStore | None = None

    async def __call__(self, job: Job) -> None:
        if self.store is not None:
            self.commits_seen.append(self.store.commits)
        if self.fail:
            raise ConnectionError("redis://:secret@10.0.0.9:6379 refused")
        self.sent.append(job)


class FakeReporter:
    """Records every status call, like the jobs table would."""

    def __init__(self) -> None:
        self.events: list[tuple[str, Any]] = []

    def started(self) -> None:
        self.events.append(("started", None))

    def progress(self, percent: int, message: str | None = None) -> None:
        self.events.append(("progress", (percent, message)))

    def retrying(self, message: str) -> None:
        self.events.append(("retrying", message))

    def succeeded(self, result: dict[str, Any] | None) -> None:
        self.events.append(("succeeded", result))

    def failed(self, error: str) -> None:
        self.events.append(("failed", error))

    def names(self) -> list[str]:
        return [name for name, _ in self.events]
