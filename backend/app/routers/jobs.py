"""Background job endpoints. The UI polls `GET /jobs/{id}` for live status.

Part of the public REST API: signed-in people OR API keys (scopes `jobs:read` /
`jobs:write`). Everything is scoped to the caller's workspace.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.core.permissions import Permission
from app.routers.deps import Jobs, allow_api_keys, get_job_service
from app.schemas.errors import error_responses
from app.schemas.jobs import ExampleJobCreate, JobList, JobRead
from app.services.organizations import Caller

router = APIRouter(prefix="/jobs", tags=["jobs"])

__all__ = ["get_job_service", "router"]  # tests override get_job_service from here

CanRead = Annotated[Caller, allow_api_keys(Permission.JOBS_READ)]
CanWrite = Annotated[Caller, allow_api_keys(Permission.JOBS_WRITE)]


@router.post(
    "/example",
    response_model=JobRead,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start the example job",
    responses=error_responses(401, 403, 429, 503),
)
async def create_example_job(data: ExampleJobCreate, caller: CanWrite, service: Jobs) -> JobRead:
    """Queue the example job. Poll `GET /jobs/{id}` to follow its progress."""
    job = await service.start_example(
        data, organization_id=caller.organization.id, user_id=caller.user_id
    )
    return JobRead.model_validate(job)


@router.get(
    "", response_model=JobList, responses=error_responses(401, 403, 429), summary="List recent jobs"
)
async def list_jobs(
    caller: CanRead,
    service: Jobs,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> JobList:
    """Newest jobs of the workspace first."""
    jobs = await service.list_recent(
        organization_id=caller.organization.id, viewer_id=caller.user_id, limit=limit
    )
    return JobList(items=[JobRead.model_validate(job) for job in jobs])


@router.get(
    "/{job_id}",
    response_model=JobRead,
    summary="Get one job",
    responses=error_responses(401, 403, 404, 429),
)
async def get_job(job_id: uuid.UUID, caller: CanRead, service: Jobs) -> JobRead:
    """Current status and progress of one job (404 for other workspaces' jobs)."""
    job = await service.get(
        job_id, organization_id=caller.organization.id, viewer_id=caller.user_id
    )
    return JobRead.model_validate(job)
