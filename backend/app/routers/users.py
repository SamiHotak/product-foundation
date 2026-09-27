"""The signed-in person's own account: profile, password, data export and deletion (GDPR)."""

import uuid

from fastapi import APIRouter, Response, status

from app.routers.deps import Accounts, CurrentUser, Deletions, Exports, OrgCtx
from app.schemas.account import PasswordChange, ProfileUpdate
from app.schemas.auth import UserRead
from app.schemas.errors import error_responses
from app.schemas.privacy import DeletionRequest, DeletionStatus, ExportList, ExportRead
from app.services.organizations import user_read

router = APIRouter(tags=["account"])


@router.patch(
    "/account/profile",
    response_model=UserRead,
    responses=error_responses(401),
    summary="Change my name",
)
async def update_profile(data: ProfileUpdate, current: CurrentUser, accounts: Accounts) -> UserRead:
    """Your name as the team sees it (members list, emails, audit log)."""
    user = await accounts.update_profile(current.user, name=data.name)
    return user_read(user)


@router.put(
    "/account/password",
    response_model=UserRead,
    responses=error_responses(400, 401, 429),
    summary="Change my password",
)
async def change_password(
    data: PasswordChange, current: CurrentUser, accounts: Accounts
) -> UserRead:
    """Needs the current password (not for Google-only accounts). Signs out other browsers."""
    user = await accounts.change_password(
        current.user,
        current.session,
        current_password=data.current_password,
        new_password=data.new_password,
    )
    return user_read(user)


@router.post(
    "/account/deletion",
    response_model=DeletionStatus,
    responses=error_responses(400, 401, 409),
    summary="Schedule deleting my account",
)
async def schedule_account_deletion(
    data: DeletionRequest, current: CurrentUser, deletions: Deletions
) -> DeletionStatus:
    """Type your email to confirm. You can cancel until the date shown."""
    user = await deletions.schedule_account(current.user, data.confirm)
    return DeletionStatus(deletion_scheduled_at=user.deletion_scheduled_at)


@router.delete(
    "/account/deletion",
    response_model=DeletionStatus,
    responses=error_responses(401),
    summary="Cancel deleting my account",
)
async def cancel_account_deletion(current: CurrentUser, deletions: Deletions) -> DeletionStatus:
    """Keep the account."""
    user = await deletions.cancel_account(current.user)
    return DeletionStatus(deletion_scheduled_at=user.deletion_scheduled_at)


@router.post(
    "/account/exports",
    response_model=ExportRead,
    status_code=status.HTTP_202_ACCEPTED,
    responses=error_responses(401, 429, 503),
    summary="Export my data (ZIP)",
)
async def export_account(ctx: OrgCtx, exports: Exports) -> ExportRead:
    """Everything we store about you. Follow the job, then download the ZIP."""
    return await exports.start_account_export(ctx)


@router.get(
    "/exports", response_model=ExportList, responses=error_responses(401), summary="My exports"
)
async def list_exports(ctx: OrgCtx, exports: Exports) -> ExportList:
    """Your exports, plus this workspace's exports if you may export it."""
    return ExportList(items=await exports.list_exports(ctx))


@router.get(
    "/exports/{export_id}/download",
    responses={
        200: {"content": {"application/zip": {}}, "description": "The ZIP file"},
        **error_responses(401, 404, 409),
    },
    response_class=Response,
    summary="Download an export",
)
async def download_export(export_id: uuid.UUID, ctx: OrgCtx, exports: Exports) -> Response:
    """The ZIP file. Only for the person (or workspace admins) it belongs to."""
    export = await exports.download(ctx, export_id)
    assert export.content is not None
    return Response(
        content=export.content,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{export.filename}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
