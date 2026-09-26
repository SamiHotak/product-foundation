"""Workspaces of the signed-in user."""

from fastapi import APIRouter, status

from app.routers.deps import CurrentUser, Orgs
from app.schemas.auth import OrganizationCreate, OrganizationRead
from app.schemas.errors import error_responses

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.get(
    "",
    response_model=list[OrganizationRead],
    responses=error_responses(401),
    summary="My workspaces",
)
async def list_organizations(current: CurrentUser, orgs: Orgs) -> list[OrganizationRead]:
    """Only workspaces you are a member of."""
    return await orgs.list_for_user(current.user)


@router.post(
    "",
    response_model=OrganizationRead,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(401),
    summary="Create a workspace",
)
async def create_organization(
    data: OrganizationCreate, current: CurrentUser, orgs: Orgs
) -> OrganizationRead:
    """You become its owner, and it becomes your active workspace."""
    return await orgs.create(current.user, current.session, data.name)
