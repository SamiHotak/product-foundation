"""Invites: sent by owners/admins, opened by the invited person (email link)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Request, Response, status

from app.core.permissions import Permission
from app.models.organization import Role
from app.routers.auth import RateLimited, start_session
from app.routers.deps import AppSettings, CurrentUser, Invites, Orgs, Sessions, require
from app.schemas.auth import MeResponse
from app.schemas.errors import error_responses
from app.schemas.team import (
    InviteCreate,
    InviteList,
    InvitePreview,
    InviteRead,
    InviteSignup,
    InviteTokenRequest,
)
from app.services.organizations import OrgContext

router = APIRouter(tags=["invites"])

CanInvite = Annotated[OrgContext, require(Permission.MEMBERS_INVITE)]


# --- workspace side -----------------------------------------------------------------------


@router.get(
    "/organizations/current/invites",
    response_model=InviteList,
    responses=error_responses(401, 403),
    summary="Open invites",
)
async def list_invites(ctx: CanInvite, invites: Invites) -> InviteList:
    """Invites nobody has accepted yet (owners and admins)."""
    return InviteList(items=await invites.list_open(ctx))


@router.post(
    "/organizations/current/invites",
    response_model=InviteRead,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(401, 403, 409, 429),
    summary="Invite someone by email",
)
async def create_invite(data: InviteCreate, ctx: CanInvite, invites: Invites) -> InviteRead:
    """Sends an email with a link. Inviting the same email again replaces the old invite."""
    return await invites.create(ctx, str(data.email), Role(data.role))


@router.post(
    "/organizations/current/invites/{invite_id}/resend",
    response_model=InviteRead,
    responses=error_responses(401, 403, 404, 429),
    summary="Send an invite again",
)
async def resend_invite(invite_id: uuid.UUID, ctx: CanInvite, invites: Invites) -> InviteRead:
    """New link, new expiry date. The old link stops working."""
    return await invites.resend(ctx, invite_id)


@router.delete(
    "/organizations/current/invites/{invite_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=error_responses(401, 403, 404),
    summary="Cancel an invite",
)
async def revoke_invite(invite_id: uuid.UUID, ctx: CanInvite, invites: Invites) -> Response:
    """The link stops working."""
    await invites.revoke(ctx, invite_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- invited person's side ----------------------------------------------------------------


@router.post(
    "/invites/preview",
    response_model=InvitePreview,
    dependencies=RateLimited,
    responses=error_responses(400, 429),
    summary="What an invite link is for",
)
async def preview_invite(data: InviteTokenRequest, invites: Invites) -> InvitePreview:
    """Workspace name, who invited you, and whether to sign in or create an account."""
    return await invites.preview(data.token)


@router.post(
    "/invites/accept",
    response_model=MeResponse,
    dependencies=RateLimited,
    responses=error_responses(400, 401, 403, 429),
    summary="Accept an invite (signed in)",
)
async def accept_invite(
    data: InviteTokenRequest, current: CurrentUser, invites: Invites, orgs: Orgs
) -> MeResponse:
    """Only for the account with the invited email. The workspace becomes your active one."""
    await invites.accept(data.token, current.user, current.session)
    return await orgs.me(current.user, current.session)


@router.post(
    "/invites/signup",
    response_model=MeResponse,
    dependencies=RateLimited,
    responses=error_responses(400, 409, 429),
    summary="Create an account from an invite (signs in)",
)
async def signup_with_invite(
    data: InviteSignup,
    request: Request,
    response: Response,
    invites: Invites,
    sessions: Sessions,
    orgs: Orgs,
    settings: AppSettings,
) -> MeResponse:
    """The invite link proves the email address, so no confirmation email is needed."""
    user, org = await invites.signup(token=data.token, name=data.name, password=data.password)
    return await start_session(
        request, response, user, sessions, orgs, settings, organization_id=org.id
    )
