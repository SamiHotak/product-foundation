"""Jobs end to end against real Postgres: API -> job row -> task -> status in the API.

The task runs in-process (instead of through Redis) but writes to the real database
with the real DbJobReporter. The e2e test in CI covers the real worker.
"""

import asyncio
import uuid
from collections.abc import Iterator
from typing import Annotated

import pytest
from fastapi import Depends
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db, sync_session
from app.models.job import Job, JobStatus
from app.models.organization import Organization
from app.repositories.jobs import JobRepository, SyncJobRepository
from app.routers.jobs import get_job_service
from app.services.jobs import JobService
from app.workers.celery_app import celery_app
from app.workers.jobs import DbJobReporter
from app.workers.tasks import example_task
from tests.helpers import World, build_world

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_db")]


@pytest.fixture(autouse=True)
def eager() -> Iterator[None]:
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_store_eager_result = False
    yield
    celery_app.conf.task_always_eager = False


@pytest.fixture
def world() -> World:
    """App whose job queue runs the task right away (in a thread)."""
    world = build_world()

    async def run_now(job: Job) -> None:
        kwargs = {"job_id": str(job.id), **job.params, "delay_seconds": 0}
        await asyncio.to_thread(example_task.apply, kwargs=kwargs, task_id=str(job.id))

    def service(session: Annotated[AsyncSession, Depends(get_db)]) -> JobService:
        return JobService(JobRepository(session), run_now)

    world.app.dependency_overrides[get_job_service] = service
    return world


def _org_id() -> uuid.UUID:
    with sync_session() as session:
        org = Organization(name="Test org")
        session.add(org)
        session.flush()
        return org.id


async def test_example_job_runs_to_done(world: World) -> None:
    async with world.client() as c:
        await world.signup_and_verify(c, "a@example.com")
        created = await c.post("/api/jobs/example", json={"steps": 4})
        assert created.status_code == 202, created.text
        job = (await c.get(f"/api/jobs/{created.json()['id']}")).json()
    assert job["status"] == "done"
    assert job["progress"] == 100
    assert job["attempts"] == 1
    assert job["message"] == "Finished 4 steps."
    assert job["result"] == {"steps": 4, "message": "Finished 4 steps."}
    assert job["finished_at"] >= job["started_at"]


async def test_failing_job_is_failed_with_safe_error(world: World) -> None:
    async with world.client() as c:
        await world.signup_and_verify(c, "a@example.com")
        created = await c.post("/api/jobs/example", json={"steps": 2, "fail": True})
        job = (await c.get(f"/api/jobs/{created.json()['id']}")).json()
    assert job["status"] == "failed"
    assert job["progress"] == 50
    assert job["error"] == "Stopped at step 2 of 2 because you asked it to fail."
    assert job["message"] is None


def test_reporter_updates_the_row(clean_db: None) -> None:
    org_id = _org_id()
    with sync_session() as session:
        job_id = (
            SyncJobRepository(session).create(kind="example", params={}, organization_id=org_id).id
        )
    reporter = DbJobReporter(str(job_id))
    reporter.started()
    reporter.progress(40, "Reading files")
    reporter.retrying("Retrying (attempt 2 of 4).")
    reporter.started()
    reporter.progress(250, None)  # clamped to 100
    reporter.succeeded({"message": "All good"})
    reporter.progress(10, "late update after done")  # ignored
    with sync_session() as session:
        job = SyncJobRepository(session).get(job_id)
        assert job is not None
        assert job.status is JobStatus.DONE
        assert (job.attempts, job.progress, job.message) == (2, 100, "All good")


def test_reporter_ignores_missing_job(clean_db: None) -> None:
    DbJobReporter(str(uuid.uuid4())).started()  # logs a warning, does not crash


def test_database_rejects_invalid_progress(clean_db: None) -> None:
    org_id = _org_id()
    with pytest.raises(IntegrityError), sync_session() as session:
        job = SyncJobRepository(session).create(kind="example", params={}, organization_id=org_id)
        job.progress = 101
        session.flush()


def test_job_needs_an_organization(clean_db: None) -> None:
    with pytest.raises(IntegrityError), sync_session() as session:
        SyncJobRepository(session).create(kind="example", params={}, organization_id=uuid.uuid4())


def test_cleanup_auth_removes_expired_sessions(clean_db: None) -> None:
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import func, select

    from app.models.session import UserSession
    from app.models.user import User
    from app.workers.tasks import cleanup_auth

    now = datetime.now(UTC)
    with sync_session() as session:
        user = User(email="c@example.com", name="C")
        session.add(user)
        session.flush()
        for expires in (now - timedelta(days=1), now + timedelta(days=1)):
            session.add(
                UserSession(
                    token_hash=str(expires), user_id=user.id, expires_at=expires, last_seen_at=now
                )
            )
    assert cleanup_auth.apply().get() == {"sessions": 1, "tokens": 0}
    with sync_session() as session:
        assert session.scalar(select(func.count()).select_from(UserSession)) == 1
