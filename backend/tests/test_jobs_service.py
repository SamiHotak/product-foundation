"""JobService tests with an in-memory store and a fake queue."""

import uuid

import pytest

from app.core.errors import NotFoundError, ServiceUnavailableError
from app.models.job import JobStatus
from app.schemas.jobs import ExampleJobCreate
from app.services.jobs import QUEUE_DOWN_ERROR, JobService
from tests.fakes import FakeDispatcher, FakeJobStore


def _service(*, fail: bool = False) -> tuple[JobService, FakeJobStore, FakeDispatcher]:
    store = FakeJobStore()
    dispatcher = FakeDispatcher(fail=fail)
    dispatcher.store = store
    return JobService(store, dispatcher), store, dispatcher


async def test_start_example_saves_then_dispatches() -> None:
    service, _store, dispatcher = _service()
    job = await service.start_example(ExampleJobCreate(steps=3))
    assert job.status is JobStatus.QUEUED
    assert job.kind == "example"
    assert job.params == {"steps": 3, "fail": False}
    assert dispatcher.sent == [job]
    # The row was committed BEFORE the task was sent (a fast worker must find it).
    assert dispatcher.commits_seen == [1]


async def test_queue_down_marks_job_failed_and_raises_503() -> None:
    service, store, _ = _service(fail=True)
    with pytest.raises(ServiceUnavailableError) as exc_info:
        await service.start_example(ExampleJobCreate())
    job = next(iter(store.jobs.values()))
    assert job.status is JobStatus.FAILED
    assert job.error == QUEUE_DOWN_ERROR
    # No connection details leak into the job or the user message.
    assert "secret" not in (job.error or "")
    assert "secret" not in exc_info.value.message
    assert store.commits == 2


async def test_unknown_kind_is_a_programming_error() -> None:
    service, _, _ = _service()
    with pytest.raises(ValueError, match="registry"):
        await service.enqueue("does-not-exist", {})


async def test_get_missing_job_raises_not_found() -> None:
    service, _, _ = _service()
    with pytest.raises(NotFoundError):
        await service.get(uuid.uuid4())


async def test_list_recent_is_newest_first_and_limited() -> None:
    service, _, _ = _service()
    await service.start_example(ExampleJobCreate(steps=1))
    second = await service.start_example(ExampleJobCreate(steps=2))
    assert await service.list_recent(limit=1) == [second]
