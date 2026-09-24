"""Celery task tests (run the task function directly, no broker needed)."""

from typing import Any

import pytest

from app.workers.celery_app import celery_app
from app.workers.tasks import example_task, heartbeat


@pytest.fixture(autouse=True)
def eager() -> Any:
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_store_eager_result = False
    yield
    celery_app.conf.task_always_eager = False


def test_example_task_reports_progress_and_returns_result(monkeypatch: pytest.MonkeyPatch) -> None:
    updates: list[dict[str, Any]] = []
    monkeypatch.setattr(
        example_task, "update_state", lambda state, meta: updates.append({"state": state, **meta})
    )
    result = example_task.apply(kwargs={"steps": 4, "delay_seconds": 0}).get()
    assert result == {"steps": 4, "progress": 100, "message": "Finished 4 steps."}
    assert [u["progress"] for u in updates] == [25, 50, 75, 100]
    assert all(u["state"] == "PROGRESS" for u in updates)


def test_example_task_rejects_bad_input() -> None:
    with pytest.raises(ValueError, match="steps"):
        example_task.apply(kwargs={"steps": 0}).get()


def test_heartbeat() -> None:
    assert heartbeat.apply().get() == "ok"


def test_beat_schedule_has_heartbeat() -> None:
    schedule = celery_app.conf.beat_schedule
    assert schedule["heartbeat-every-5-minutes"]["task"] == "app.workers.tasks.heartbeat"
