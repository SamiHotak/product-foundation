"""Job service: start background jobs and read their status."""

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from app.core.errors import NotFoundError, ServiceUnavailableError
from app.core.logging import get_logger
from app.models.job import Job
from app.repositories.jobs import JobStore
from app.schemas.jobs import ExampleJobCreate
from app.workers.registry import JOB_TASKS

logger = get_logger(__name__)

Dispatcher = Callable[[Job], Awaitable[None]]

QUEUE_DOWN_ERROR = "Could not queue the job because the job queue was not reachable."


class JobService:
    """Creates jobs, hands them to the queue, and reads their status."""

    def __init__(self, store: JobStore, dispatch: Dispatcher) -> None:
        self._store = store
        self._dispatch = dispatch

    async def enqueue(
        self,
        kind: str,
        params: dict[str, Any],
        *,
        organization_id: uuid.UUID,
        created_by_id: uuid.UUID | None,
    ) -> Job:
        """Save a queued job, then send it to the workers.

        The row is committed BEFORE the task is sent, so a fast worker always finds it.
        If sending fails, the job is marked failed and the caller gets a 503.
        """
        if kind not in JOB_TASKS:
            raise ValueError(f"Unknown job kind: {kind!r}. Register it in app/workers/registry.py")
        job = await self._store.create(
            kind=kind,
            params=params,
            organization_id=organization_id,
            created_by_id=created_by_id,
        )
        await self._store.commit()
        try:
            await self._dispatch(job)
        except Exception as exc:
            logger.error("job_dispatch_failed", job_id=str(job.id), error_type=type(exc).__name__)
            await self._store.mark_failed(job, QUEUE_DOWN_ERROR)
            await self._store.commit()
            raise ServiceUnavailableError(
                "The job queue is not reachable right now. Try again in a minute."
            ) from exc
        logger.info("job_queued", job_id=str(job.id), kind=kind)
        return job

    async def start_example(
        self, data: ExampleJobCreate, *, organization_id: uuid.UUID, user_id: uuid.UUID
    ) -> Job:
        """Start the example job in this organization."""
        return await self.enqueue(
            "example", data.model_dump(), organization_id=organization_id, created_by_id=user_id
        )

    async def get(self, job_id: uuid.UUID, *, organization_id: uuid.UUID) -> Job:
        """Return one job of this organization or raise NotFoundError."""
        job = await self._store.get(job_id, organization_id=organization_id)
        if job is None:
            raise NotFoundError("This job does not exist.")
        return job

    async def list_recent(self, *, organization_id: uuid.UUID, limit: int = 20) -> list[Job]:
        """Newest jobs of this organization first."""
        return await self._store.list_recent(organization_id=organization_id, limit=limit)
