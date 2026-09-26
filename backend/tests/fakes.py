"""In-memory fakes (no Postgres, Redis, mail server or Google)."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from app.models.job import Job, JobStatus


class FakeJobStore:
    """Implements app.repositories.jobs.JobStore in memory."""

    def __init__(self) -> None:
        self.jobs: dict[uuid.UUID, Job] = {}
        self.commits = 0

    async def create(
        self,
        *,
        kind: str,
        params: dict[str, Any],
        organization_id: uuid.UUID,
        created_by_id: uuid.UUID | None,
    ) -> Job:
        # Strictly increasing timestamps, so ordering is deterministic.
        now = datetime.now(UTC) + timedelta(microseconds=len(self.jobs))
        job = Job(
            id=uuid.uuid4(),
            organization_id=organization_id,
            created_by_id=created_by_id,
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

    @staticmethod
    def _visible(job: Job, viewer_id: uuid.UUID | None) -> bool:
        from app.workers.registry import PRIVATE_JOB_KINDS

        return job.kind not in PRIVATE_JOB_KINDS or (
            viewer_id is not None and job.created_by_id == viewer_id
        )

    async def get(
        self, job_id: uuid.UUID, *, organization_id: uuid.UUID, viewer_id: uuid.UUID | None
    ) -> Job | None:
        job = self.jobs.get(job_id)
        if job is None or job.organization_id != organization_id:
            return None
        return job if self._visible(job, viewer_id) else None

    async def list_recent(
        self, *, organization_id: uuid.UUID, viewer_id: uuid.UUID | None, limit: int
    ) -> list[Job]:
        mine = [
            j
            for j in self.jobs.values()
            if j.organization_id == organization_id and self._visible(j, viewer_id)
        ]
        return sorted(mine, key=lambda j: j.created_at, reverse=True)[:limit]

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


class FakeEmailSender:
    """Records emails instead of sending them."""

    def __init__(self) -> None:
        from app.services.email import EmailMessage

        self.sent: list[EmailMessage] = []

    async def send(self, message: Any) -> None:
        self.sent.append(message)

    def last_to(self, email: str) -> Any:
        found = [m for m in self.sent if m.to.lower() == email.lower()]
        assert found, f"no email to {email}"
        return found[-1]

    def link_token(self, email: str) -> str:
        """The token from the link in the newest email to this address."""
        import re

        match = re.search(r"token=([A-Za-z0-9_-]+)", self.last_to(email).text)
        assert match, "no token link in email"
        return match.group(1)


class FakeGoogleClient:
    """Pretends to be Google. Set `profile` (or `error`) before the callback."""

    def __init__(self) -> None:
        from app.services.google_oauth import GoogleProfile

        self.profile: GoogleProfile | None = None
        self.error: Exception | None = None
        self.last_verifier: str | None = None

    def authorize_url(self, *, state: str, code_challenge: str, redirect_uri: str) -> str:
        return f"https://accounts.example/auth?state={state}&challenge={code_challenge}"

    async def fetch_profile(self, *, code: str, code_verifier: str, redirect_uri: str) -> Any:
        self.last_verifier = code_verifier
        if self.error:
            raise self.error
        assert self.profile is not None
        return self.profile
