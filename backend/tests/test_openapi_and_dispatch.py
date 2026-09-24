"""OpenAPI export (source of the typed frontend client) and queue dispatch."""

import json
import uuid
from typing import Any

import pytest

from app.models.job import Job
from app.scripts.export_openapi import build_schema
from app.workers import dispatch
from app.workers.celery_app import celery_app


def test_openapi_export_is_stable_and_complete() -> None:
    first, second = build_schema(), build_schema()
    assert first == second  # same code -> same file -> clean `git diff` in CI
    schema = json.loads(first)
    operation_ids = {op["operationId"] for path in schema["paths"].values() for op in path.values()}
    assert {"liveness", "readiness", "create_example_job", "list_jobs", "get_job"} <= operation_ids
    # Errors are typed with the standard envelope.
    get_job = schema["paths"]["/api/jobs/{job_id}"]["get"]["responses"]
    assert get_job["404"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/ErrorResponse"
    )


def test_send_job_uses_job_id_as_task_id(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: dict[str, Any] = {}

    def fake_send_task(name: str, **kwargs: Any) -> None:
        sent.update(name=name, **kwargs)

    monkeypatch.setattr(celery_app, "send_task", fake_send_task)
    job_id = uuid.uuid4()
    dispatch.send_job(job_id, "example", {"steps": 2, "fail": False})
    assert sent["name"] == "app.workers.tasks.example_task"
    assert sent["task_id"] == str(job_id)
    assert sent["kwargs"] == {"job_id": str(job_id), "steps": 2, "fail": False}
    assert sent["retry_policy"]["max_retries"] <= 3  # fail fast when Redis is down
    assert sent["ignore_result"] is True  # no result-backend round trip


async def test_celery_dispatch_runs_in_a_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[uuid.UUID, str, dict[str, Any]]] = []
    monkeypatch.setattr(dispatch, "send_job", lambda *args: calls.append(args))
    job = Job(id=uuid.uuid4(), kind="example", params={"steps": 1})
    await dispatch.celery_dispatch(job)
    assert calls == [(job.id, "example", {"steps": 1})]


def test_export_writes_file_with_lf_endings(tmp_path: Any) -> None:
    from app.scripts.export_openapi import main

    out = tmp_path / "openapi.json"
    main(["--out", str(out)])
    raw = out.read_bytes()
    assert b"\r\n" not in raw
    assert raw.decode() == build_schema()
