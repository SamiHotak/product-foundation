"""Example tasks.

`example_task` shows the pattern every long job will use: report progress,
retry on temporary errors with backoff, return a small JSON result.
In phase 1B the progress is also written to the `jobs` table for the live UI.
"""

import time
from typing import Any

from app.core.logging import get_logger
from app.workers.celery_app import celery_app

logger = get_logger(__name__)


class TemporaryError(Exception):
    """An error worth retrying (network blip, rate limit, ...)."""


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="app.workers.tasks.example_task",
    autoretry_for=(TemporaryError,),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
    max_retries=3,
)
def example_task(self: Any, steps: int = 5, delay_seconds: float = 1.0) -> dict[str, Any]:
    """Count through `steps`, reporting progress after each one."""
    if not 1 <= steps <= 100:
        raise ValueError("steps must be between 1 and 100")
    logger.info("example_task_started", task_id=self.request.id, steps=steps)
    for step in range(1, steps + 1):
        time.sleep(delay_seconds)
        progress = round(step / steps * 100)
        self.update_state(
            state="PROGRESS", meta={"step": step, "steps": steps, "progress": progress}
        )
    logger.info("example_task_done", task_id=self.request.id)
    return {"steps": steps, "progress": 100, "message": f"Finished {steps} steps."}


@celery_app.task(name="app.workers.tasks.heartbeat")  # type: ignore[untyped-decorator]
def heartbeat() -> str:
    """Scheduled by beat. Proves the scheduler and worker are alive (visible in logs)."""
    logger.info("heartbeat")
    return "ok"
