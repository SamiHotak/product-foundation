"""Helpers for integration tests: a real app on the test database with fake outside services."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Annotated, Any

from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.rate_limit import MemoryRateLimiter, get_rate_limiter
from app.db.session import get_db
from app.main import create_app
from app.models.job import Job
from app.repositories.jobs import JobRepository
from app.routers.deps import get_email_sender, get_google_client
from app.routers.jobs import get_job_service
from app.services.jobs import JobService
from app.workers.registry import JOB_TASKS
from tests.fakes import FakeEmailSender, FakeGoogleClient

PASSWORD = "correct horse battery"


@dataclass
class World:
    """The app plus every fake, so tests can look inside."""

    app: FastAPI
    email: FakeEmailSender = field(default_factory=FakeEmailSender)
    limiter: MemoryRateLimiter = field(default_factory=MemoryRateLimiter)
    google: FakeGoogleClient = field(default_factory=FakeGoogleClient)
    dispatched: list[Job] = field(default_factory=list)

    @asynccontextmanager
    async def client(self, **headers: str) -> AsyncIterator[AsyncClient]:
        """A browser-like client with its own cookie jar."""
        transport = ASGITransport(app=self.app, raise_app_exceptions=False)
        async with AsyncClient(
            transport=transport, base_url="http://test", headers=headers, follow_redirects=False
        ) as c:
            yield c

    async def signup_and_verify(
        self, c: AsyncClient, email: str, name: str = "Ezat Test"
    ) -> dict[str, Any]:
        """Sign up, open the email link, return /me. The client is signed in afterwards."""
        res = await c.post(
            "/api/auth/signup", json={"name": name, "email": email, "password": PASSWORD}
        )
        assert res.status_code == 202, res.text
        res = await c.post("/api/auth/verify-email", json={"token": self.email.link_token(email)})
        assert res.status_code == 200, res.text
        body: dict[str, Any] = res.json()
        return body

    def settings(self, **changes: Any) -> Settings:
        """Use changed settings for the rest of the test (e.g. lower limits)."""
        changed = get_settings().model_copy(update=changes)
        self.app.dependency_overrides[get_settings] = lambda: changed
        return changed

    async def run_jobs(self) -> None:
        """Run every queued job now, in-process, with the real worker code and database."""
        import app.workers.tasks  # noqa: F401 - registers the tasks
        from app.workers.celery_app import celery_app

        pending, self.dispatched[:] = list(self.dispatched), []
        for job in pending:
            task = celery_app.tasks[JOB_TASKS[job.kind]]
            kwargs: dict[str, Any] = {"job_id": str(job.id), **job.params}
            if job.kind == "example":
                kwargs["delay_seconds"] = 0
            await asyncio.to_thread(task.apply, kwargs=kwargs, task_id=str(job.id))

    async def invite_and_join(
        self,
        inviter: AsyncClient,
        invitee: AsyncClient,
        email: str,
        role: str = "member",
        name: str = "New Person",
    ) -> dict[str, Any]:
        """Invite `email` and let `invitee` (signed out) create an account from the link."""
        res = await inviter.post(
            "/api/organizations/current/invites", json={"email": email, "role": role}
        )
        assert res.status_code == 201, res.text
        res = await invitee.post(
            "/api/invites/signup",
            json={"token": self.email.link_token(email), "name": name, "password": PASSWORD},
        )
        assert res.status_code == 200, res.text
        body: dict[str, Any] = res.json()
        return body


def build_world() -> World:
    """Real app + real test database; email, rate limits, Google and the job queue are fakes."""
    world = World(app=create_app(get_settings()))
    app = world.app

    async def dispatch(job: Job) -> None:
        world.dispatched.append(job)

    def job_service(session: Annotated[AsyncSession, Depends(get_db)]) -> JobService:
        return JobService(JobRepository(session), dispatch)

    app.dependency_overrides[get_email_sender] = lambda: world.email
    app.dependency_overrides[get_rate_limiter] = lambda: world.limiter
    app.dependency_overrides[get_google_client] = lambda: world.google
    app.dependency_overrides[get_job_service] = job_service
    return world
