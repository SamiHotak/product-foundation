"""Send a job to the Celery queue. The Celery task id is the job id."""

import asyncio
import uuid
from typing import Any

from app.models.job import Job
from app.workers.celery_app import celery_app
from app.workers.registry import JOB_TASKS

# Fail fast when Redis is down, instead of hanging the request.
_PUBLISH_RETRY_POLICY = {
    "max_retries": 2,
    "interval_start": 0,
    "interval_step": 0.2,
    "interval_max": 0.5,
}


def send_job(job_id: uuid.UUID, kind: str, params: dict[str, Any]) -> None:
    """Publish the task for this job (blocking)."""
    celery_app.send_task(
        JOB_TASKS[kind],
        kwargs={"job_id": str(job_id), **params},
        task_id=str(job_id),
        # Status and results live in the jobs table, not in Celery's result backend.
        # (Without this, a Redis outage makes the request hang ~20 s.)
        ignore_result=True,
        retry=True,
        retry_policy=_PUBLISH_RETRY_POLICY,
    )


async def celery_dispatch(job: Job) -> None:
    """Async wrapper for the API: publishing runs in a thread, not on the event loop."""
    await asyncio.to_thread(send_job, job.id, job.kind, dict(job.params))
