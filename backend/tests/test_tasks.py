"""Celery task tests: tasks run in-process (eager), job status goes to a fake reporter."""

from collections.abc import Iterator
from typing import Any

import pytest

from app.workers import jobs as worker_jobs
from app.workers.celery_app import celery_app
from app.workers.jobs import JobFailedError, TemporaryError, safe_error_message
from app.workers.tasks import example_task, heartbeat
from tests.fakes import FakeReporter

JOB_ID = "11111111-2222-3333-4444-555555555555"


@pytest.fixture(autouse=True)
def eager() -> Iterator[None]:
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_store_eager_result = False
    yield
    celery_app.conf.task_always_eager = False


@pytest.fixture
def reporter(monkeypatch: pytest.MonkeyPatch) -> FakeReporter:
    fake = FakeReporter()
    monkeypatch.setattr(worker_jobs, "make_reporter", lambda job_id: fake)
    # tasks.py imported the name directly, so patch it there too.
    monkeypatch.setattr("app.workers.tasks.make_reporter", lambda job_id: fake)
    return fake


def _run(**kwargs: Any) -> Any:
    return example_task.apply(kwargs={"job_id": JOB_ID, "delay_seconds": 0, **kwargs})


def test_example_task_reports_life_cycle(reporter: FakeReporter) -> None:
    result = _run(steps=4).get()
    assert result == {"steps": 4, "message": "Finished 4 steps."}
    assert reporter.names() == ["started", *["progress"] * 4, "succeeded"]
    progress = [value for name, value in reporter.events if name == "progress"]
    assert [p for p, _ in progress] == [25, 50, 75, 100]
    assert progress[0][1] == "Step 1 of 4"
    assert reporter.events[-1] == ("succeeded", result)


def test_example_task_fail_flag_gives_user_facing_error(reporter: FakeReporter) -> None:
    outcome = _run(steps=4, fail=True)
    assert outcome.failed()
    assert reporter.names()[-1] == "failed"
    assert reporter.events[-1][1] == "Stopped at step 3 of 4 because you asked it to fail."
    # Progress stopped at 50% (steps 1 and 2 finished).
    assert [v[0] for n, v in reporter.events if n == "progress"] == [25, 50]


def test_example_task_rejects_bad_input(reporter: FakeReporter) -> None:
    assert _run(steps=0).failed()
    assert reporter.events[-1] == ("failed", "Steps must be between 1 and 100.")


def test_temporary_error_is_retried_then_succeeds(
    reporter: FakeReporter, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = {"n": 0}
    real_progress = reporter.progress

    def flaky_progress(percent: int, message: str | None = None) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise TemporaryError("network blip")
        real_progress(percent, message)

    monkeypatch.setattr(reporter, "progress", flaky_progress)
    monkeypatch.setattr(example_task, "retry_backoff", False)  # no waiting in tests
    _run(steps=2)
    names = reporter.names()
    assert "retrying" in names
    assert names.count("started") == 2  # first attempt + one retry
    assert names[-1] == "succeeded"
    retry_msg = next(v for n, v in reporter.events if n == "retrying")
    assert "attempt 2 of 4" in retry_msg


def test_unexpected_error_shows_safe_message(reporter: FakeReporter) -> None:
    def boom(percent: int, message: str | None = None) -> None:
        raise RuntimeError("db password=hunter2 at 10.0.0.5")

    reporter.progress = boom  # type: ignore[method-assign]
    assert _run(steps=1).failed()
    error = reporter.events[-1][1]
    assert "hunter2" not in error
    assert JOB_ID in error


def test_safe_error_message() -> None:
    assert safe_error_message(JobFailedError("Invoice has no total."), "j1") == (
        "Invoice has no total."
    )
    assert "boom" not in safe_error_message(RuntimeError("boom"), "j1")


def test_task_without_job_id_skips_reporting(reporter: FakeReporter) -> None:
    assert heartbeat.apply().get() == "ok"
    assert reporter.events == []


def test_beat_schedule_has_heartbeat() -> None:
    schedule = celery_app.conf.beat_schedule
    assert schedule["heartbeat-every-5-minutes"]["task"] == "app.workers.tasks.heartbeat"
