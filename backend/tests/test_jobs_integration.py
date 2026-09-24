"""Jobs end to end against real Postgres: API -> job row -> task -> status in the API.

The task runs in-process (instead of through Redis) but writes to the real database
with the real DbJobReporter. The e2e test in CI covers the real worker.
Skipped unless RUN_INTEGRATION=1 (`make test` and CI set it).
"""

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Iterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.core.config import get_settings
from app.db.session import get_async_engine, get_db, sync_session
from app.main import create_app
from app.models.job import Job, JobStatus
from app.repositories.jobs import JobRepository, SyncJobRepository
from app.routers.jobs import get_job_service
from app.services.jobs import JobService
from app.workers.celery_app import celery_app
from app.workers.jobs import DbJobReporter
from app.workers.tasks import example_task

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("RUN_INTEGRATION") != "1", reason="set RUN_INTEGRATION=1"),
]


@pytest.fixture(autouse=True)
def eager() -> Iterator[None]:
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_store_eager_result = False
    yield
    celery_app.conf.task_always_eager = False


@pytest.fixture
def created_ids() -> Iterator[list[uuid.UUID]]:
    """Delete only the rows this test made (the dev database may hold your own jobs)."""
    ids: list[uuid.UUID] = []
    yield ids
    if ids:
        with sync_session() as session:
            session.execute(delete(Job).where(Job.id.in_(ids)))


async def _run_task_now(job: Job) -> None:
    """Dispatcher that runs the task right away in a thread (no Redis round trip)."""
    kwargs = {"job_id": str(job.id), **job.params, "delay_seconds": 0}
    await asyncio.to_thread(example_task.apply, kwargs=kwargs, task_id=str(job.id))


@pytest.fixture
async def app_with_inline_worker(created_ids: list[uuid.UUID]) -> AsyncIterator[FastAPI]:
    app = create_app(get_settings())

    async def service() -> AsyncIterator[JobService]:
        async for db in get_db():
            repo = JobRepository(db)

            async def dispatch(job: Job) -> None:
                created_ids.append(job.id)
                await _run_task_now(job)

            yield JobService(repo, dispatch)

    app.dependency_overrides[get_job_service] = service
    yield app
    await get_async_engine().dispose()


async def test_example_job_runs_to_done(app_with_inline_worker: FastAPI) -> None:
    transport = ASGITransport(app=app_with_inline_worker)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        created = await c.post("/api/jobs/example", json={"steps": 4})
        assert created.status_code == 202, created.text
        job = (await c.get(f"/api/jobs/{created.json()['id']}")).json()
        listed = (await c.get("/api/jobs")).json()["items"]
    assert job["status"] == "done"
    assert job["progress"] == 100
    assert job["attempts"] == 1
    assert job["message"] == "Finished 4 steps."
    assert job["result"] == {"steps": 4, "message": "Finished 4 steps."}
    assert job["started_at"] is not None
    assert job["finished_at"] >= job["started_at"]
    assert job["updated_at"] > job["created_at"]
    assert job["id"] in [j["id"] for j in listed]


async def test_failing_job_is_failed_with_safe_error(app_with_inline_worker: FastAPI) -> None:
    transport = ASGITransport(app=app_with_inline_worker)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        created = await c.post("/api/jobs/example", json={"steps": 2, "fail": True})
        job = (await c.get(f"/api/jobs/{created.json()['id']}")).json()
    assert job["status"] == "failed"
    assert job["progress"] == 50
    assert job["error"] == "Stopped at step 2 of 2 because you asked it to fail."
    assert job["message"] is None
    assert job["finished_at"] is not None


def test_reporter_updates_the_row(created_ids: list[uuid.UUID]) -> None:
    with sync_session() as session:
        job_id = SyncJobRepository(session).create(kind="example", params={}).id
    created_ids.append(job_id)
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
        assert job.attempts == 2
        assert job.progress == 100
        assert job.message == "All good"
        assert job.result == {"message": "All good"}


def test_reporter_ignores_missing_job() -> None:
    DbJobReporter(str(uuid.uuid4())).started()  # logs a warning, does not crash


def test_database_rejects_invalid_progress(created_ids: list[uuid.UUID]) -> None:
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError), sync_session() as session:
        job = SyncJobRepository(session).create(kind="example", params={})
        created_ids.append(job.id)
        job.progress = 101
        session.flush()
