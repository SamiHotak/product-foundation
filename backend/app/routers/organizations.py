"""Workspaces of the signed-in user, and settings of the active workspace."""

from typing import Annotated

from fastapi import APIRouter, Response, status

from app.core.permissions import Permission
from app.routers.deps import CurrentUser, Deletions, Exports, Members, OrgCtx, Orgs, require
from app.schemas.auth import OrganizationCreate, OrganizationRead
from app.schemas.errors import error_responses
from app.schemas.privacy import DeletionRequest, DeletionStatus, ExportRead
from app.schemas.team import MemberList, OrganizationUpdate, TransferOwnership
from app.services.organizations import OrgContext, organization_read

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


@router.patch(
    "/current",
    response_model=OrganizationRead,
    responses=error_responses(401, 403),
    summary="Rename the active workspace",
)
async def update_organization(
    data: OrganizationUpdate,
    ctx: Annotated[OrgContext, require(Permission.ORG_UPDATE)],
    orgs: Orgs,
) -> OrganizationRead:
    """Owners and admins."""
    return await orgs.rename(ctx, data.name)


@router.post(
    "/current/leave",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=error_responses(401, 409),
    summary="Leave the active workspace",
)
async def leave_organization(ctx: OrgCtx, members: Members) -> Response:
    """You lose access. The owner can't leave (transfer ownership first)."""
    await members.leave(ctx)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/current/transfer-ownership",
    response_model=MemberList,
    responses=error_responses(401, 403, 404, 409),
    summary="Make another member the owner",
)
async def transfer_ownership(
    data: TransferOwnership,
    ctx: Annotated[OrgContext, require(Permission.OWNERSHIP_TRANSFER)],
    members: Members,
) -> MemberList:
    """Owner only. You become an admin."""
    return MemberList(items=await members.transfer_ownership(ctx, data.user_id))


@router.post(
    "/current/deletion",
    response_model=OrganizationRead,
    responses=error_responses(400, 401, 403),
    summary="Schedule deleting the active workspace",
)
async def schedule_organization_deletion(
    data: DeletionRequest,
    ctx: Annotated[OrgContext, require(Permission.ORG_DELETE)],
    deletions: Deletions,
) -> OrganizationRead:
    """Owner only. Type the workspace name to confirm. Deleted after the grace period."""
    await deletions.schedule_org(ctx, data.confirm)
    return organization_read(ctx.organization, ctx.membership)


@router.delete(
    "/current/deletion",
    response_model=DeletionStatus,
    responses=error_responses(401, 403),
    summary="Cancel deleting the active workspace",
)
async def cancel_organization_deletion(
    ctx: Annotated[OrgContext, require(Permission.ORG_DELETE)], deletions: Deletions
) -> DeletionStatus:
    """Owner only."""
    await deletions.cancel_org(ctx)
    return DeletionStatus(deletion_scheduled_at=ctx.organization.deletion_scheduled_at)


@router.post(
    "/current/exports",
    response_model=ExportRead,
    status_code=status.HTTP_202_ACCEPTED,
    responses=error_responses(401, 403, 429, 503),
    summary="Export all data of the active workspace (ZIP)",
)
async def export_organization(
    ctx: Annotated[OrgContext, require(Permission.ORG_EXPORT)], exports: Exports
) -> ExportRead:
    """Owners and admins. Follow the job, then download the ZIP."""
    return await exports.start_org_export(ctx)
