"""Background job endpoints. The UI polls `GET /jobs/{id}` for live status.

Signed-in users only; everything is scoped to the active workspace.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.repositories.jobs import JobRepository
from app.routers.deps import OrgCtx
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
    responses=error_responses(401, 503),
)
async def create_example_job(data: ExampleJobCreate, ctx: OrgCtx, service: Service) -> JobRead:
    """Queue the example job. Poll `GET /jobs/{id}` to follow its progress."""
    job = await service.start_example(
        data, organization_id=ctx.organization.id, user_id=ctx.user.id
    )
    return JobRead.model_validate(job)


@router.get("", response_model=JobList, responses=error_responses(401), summary="List recent jobs")
async def list_jobs(
    ctx: OrgCtx,
    service: Service,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> JobList:
    """Newest jobs of the active workspace first."""
    jobs = await service.list_recent(organization_id=ctx.organization.id, limit=limit)
    return JobList(items=[JobRead.model_validate(job) for job in jobs])


@router.get(
    "/{job_id}",
    response_model=JobRead,
    summary="Get one job",
    responses=error_responses(401, 404),
)
async def get_job(job_id: uuid.UUID, ctx: OrgCtx, service: Service) -> JobRead:
    """Current status and progress of one job (404 for other workspaces' jobs)."""
    return JobRead.model_validate(await service.get(job_id, organization_id=ctx.organization.id))
