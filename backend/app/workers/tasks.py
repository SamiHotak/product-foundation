"""Celery tasks.

`example_task` shows the pattern every long job uses: it is linked to a row in
the `jobs` table (base=JobTask), reports progress, retries temporary errors with
backoff, and returns a small JSON result.
"""

import time
from typing import Any

from app.core.logging import get_logger
from app.workers.celery_app import celery_app
from app.workers.jobs import JobFailedError, JobTask, TemporaryError, make_reporter

logger = get_logger(__name__)

__all__ = ["TemporaryError", "example_task", "heartbeat"]


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True,
    base=JobTask,
    name="app.workers.tasks.example_task",
    autoretry_for=(TemporaryError,),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
    max_retries=3,
)
def example_task(
    self: Any,
    job_id: str,
    steps: int = 5,
    fail: bool = False,
    delay_seconds: float = 1.0,
) -> dict[str, Any]:
    """Count through `steps`, reporting progress after each one.

    With `fail=True` it stops halfway with a user-facing error (to test the UI).
    """
    if not 1 <= steps <= 100:
        raise JobFailedError("Steps must be between 1 and 100.")
    report = make_reporter(job_id)
    logger.info("example_task_started", job_id=job_id, steps=steps, attempt=self.request.retries)
    for step in range(1, steps + 1):
        time.sleep(delay_seconds)
        if fail and step > steps // 2:
            raise JobFailedError(f"Stopped at step {step} of {steps} because you asked it to fail.")
        report.progress(round(step / steps * 100), f"Step {step} of {steps}")
    return {"steps": steps, "message": f"Finished {steps} steps."}


@celery_app.task(name="app.workers.tasks.heartbeat")  # type: ignore[untyped-decorator]
def heartbeat() -> str:
    """Scheduled by beat. Proves the scheduler and worker are alive (visible in logs)."""
    logger.info("heartbeat")
    return "ok"
