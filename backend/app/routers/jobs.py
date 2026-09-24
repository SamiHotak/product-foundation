"""Background job endpoints. The UI polls `GET /jobs/{id}` for live status.

Phase 2 adds login and organization scoping; until then this router is only
mounted when `JOBS_API_ENABLED` is true (default: everywhere except production).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.repositories.jobs import JobRepository
from app.schemas.errors import error_responses
from app.schemas.jobs import ExampleJobCreate, JobList, JobRead
from app.services.jobs import JobService
from app.workers.dispatch import celery_dispatch

router = APIRouter(prefix="/jobs", tags=["jobs"])


def get_job_service(session: Annotated[AsyncSession, Depends(get_db)]) -> JobService:
    """Dependency that builds the job service (overridden in tests)."""
    return JobService(JobRepository(session), celery_dispatch)


Service = Annotated[JobService, Depends(get_job_service)]


@router.post(
    "/example",
    response_model=JobRead,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start the example job",
    responses=error_responses(503),
)
async def create_example_job(data: ExampleJobCreate, service: Service) -> JobRead:
    """Queue the example job. Poll `GET /jobs/{id}` to follow its progress."""
    return JobRead.model_validate(await service.start_example(data))


@router.get("", response_model=JobList, summary="List recent jobs")
async def list_jobs(
    service: Service,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> JobList:
    """Newest jobs first."""
    jobs = await service.list_recent(limit)
    return JobList(items=[JobRead.model_validate(job) for job in jobs])


@router.get(
    "/{job_id}",
    response_model=JobRead,
    summary="Get one job",
    responses=error_responses(404),
)
async def get_job(job_id: uuid.UUID, service: Service) -> JobRead:
    """Current status and progress of one job."""
    return JobRead.model_validate(await service.get(job_id))
