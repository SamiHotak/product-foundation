"""Members of the active workspace."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Response, status

from app.core.permissions import Permission
from app.models.organization import Role
from app.routers.deps import Members, require
from app.schemas.errors import error_responses
from app.schemas.team import MemberList, MemberRead, MemberUpdate
from app.services.organizations import OrgContext

router = APIRouter(prefix="/organizations/current/members", tags=["members"])


@router.get("", response_model=MemberList, responses=error_responses(401), summary="List members")
async def list_members(
    ctx: Annotated[OrgContext, require(Permission.MEMBERS_READ)], members: Members
) -> MemberList:
    """Everyone in the workspace. Every member may see the team."""
    return MemberList(items=await members.list_members(ctx))


@router.patch(
    "/{user_id}",
    response_model=MemberRead,
    responses=error_responses(401, 403, 404, 409),
    summary="Change a member's role",
)
async def update_member(
    user_id: uuid.UUID,
    data: MemberUpdate,
    ctx: Annotated[OrgContext, require(Permission.MEMBERS_MANAGE)],
    members: Members,
) -> MemberRead:
    """Owners and admins. The owner's role can't be changed here."""
    return await members.change_role(ctx, user_id, Role(data.role))


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=error_responses(401, 403, 404, 409),
    summary="Remove a member",
)
async def remove_member(
    user_id: uuid.UUID,
    ctx: Annotated[OrgContext, require(Permission.MEMBERS_MANAGE)],
    members: Members,
) -> Response:
    """Owners and admins. Their account stays; they lose access to this workspace."""
    await members.remove(ctx, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
