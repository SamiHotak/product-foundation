"""The app admin area (/admin). Only app admins (superusers), signed in as themselves.

Give someone admin rights with `make admin email=...` (never through the API).
"""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query, Request, Response, status

from app.routers.deps import (
    Admin,
    AppAdmin,
    AppSettings,
    CurrentUser,
    admin_cookie_name,
    clear_session_cookie,
    client_ip,
    set_session_cookie,
)
from app.schemas.admin import (
    AdminFailedJobList,
    AdminOrganizationList,
    AdminOverview,
    AdminSubscriptionList,
    AdminUsage,
    AdminUserList,
    AiPauseUpdate,
    ImpersonationStopped,
)
from app.schemas.errors import error_responses

router = APIRouter(prefix="/admin", tags=["admin"])

Search = Annotated[str | None, Query(max_length=100)]
Limit = Annotated[int, Query(ge=1, le=500)]


@router.get(
    "/overview",
    response_model=AdminOverview,
    responses=error_responses(401, 403),
    summary="Admin overview",
)
async def admin_overview(_: AppAdmin, admin: Admin) -> AdminOverview:
    """Headline numbers of the whole app, and the AI switch."""
    return await admin.overview()


@router.get(
    "/organizations",
    response_model=AdminOrganizationList,
    responses=error_responses(401, 403),
    summary="All workspaces",
)
async def admin_organizations(
    _: AppAdmin, admin: Admin, search: Search = None, limit: Limit = 200
) -> AdminOrganizationList:
    """Workspaces with owner, plan, members and this month's usage."""
    return AdminOrganizationList(items=await admin.organizations(search, limit))


@router.get(
    "/users", response_model=AdminUserList, responses=error_responses(401, 403), summary="All users"
)
async def admin_users(
    _: AppAdmin, admin: Admin, search: Search = None, limit: Limit = 200
) -> AdminUserList:
    """Users, newest first."""
    return AdminUserList(items=await admin.users(search, limit))


@router.get(
    "/subscriptions",
    response_model=AdminSubscriptionList,
    responses=error_responses(401, 403),
    summary="All subscriptions",
)
async def admin_subscriptions(
    _: AppAdmin, admin: Admin, limit: Limit = 200
) -> AdminSubscriptionList:
    """The subscriptions table (our copy of Stripe), paid first."""
    return AdminSubscriptionList(items=await admin.subscriptions(limit))


@router.get(
    "/usage",
    response_model=AdminUsage,
    responses=error_responses(401, 403),
    summary="AI usage and cost",
)
async def admin_usage(
    _: AppAdmin,
    admin: Admin,
    month: Annotated[date | None, Query(description="Any day of the month (UTC).")] = None,
) -> AdminUsage:
    """AI requests and cost per workspace, task and model for one month."""
    return await admin.usage(month)


@router.get(
    "/jobs/failed",
    response_model=AdminFailedJobList,
    responses=error_responses(401, 403),
    summary="Failed jobs",
)
async def admin_failed_jobs(_: AppAdmin, admin: Admin, limit: Limit = 100) -> AdminFailedJobList:
    """Jobs that failed for good (the dead-letter list), newest first."""
    return AdminFailedJobList(items=await admin.failed_jobs(limit))


@router.post(
    "/jobs/{job_id}/retry",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=error_responses(401, 403, 404, 409, 503),
    summary="Retry a failed job",
)
async def admin_retry_job(job_id: uuid.UUID, current: AppAdmin, admin: Admin) -> Response:
    """Queues the same job again (same id, same parameters)."""
    await admin.retry_job(current.user, job_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put(
    "/ai",
    response_model=AdminOverview,
    responses=error_responses(401, 403),
    summary="Pause or resume all AI",
)
async def admin_set_ai(data: AiPauseUpdate, current: AppAdmin, admin: Admin) -> AdminOverview:
    """The kill switch: while paused, every AI request is refused (no restart needed)."""
    await admin.set_ai_paused(current.user, data.paused)
    return await admin.overview()


@router.post(
    "/users/{user_id}/impersonate",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=error_responses(401, 403, 404, 409),
    summary="View the app as a user",
)
async def admin_impersonate(
    user_id: uuid.UUID,
    request: Request,
    current: AppAdmin,
    admin: Admin,
    settings: AppSettings,
) -> Response:
    """Signs this browser in as the user for a limited time. Your own session waits."""
    token = await admin.start_impersonation(
        current.user,
        user_id,
        ip=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    minutes = settings.impersonation_minutes
    own = request.cookies.get(settings.session_cookie_name, "")
    set_session_cookie(
        response, own, settings, name=admin_cookie_name(settings), max_age=minutes * 60
    )
    set_session_cookie(response, token, settings, max_age=minutes * 60)
    return response


@router.post(
    "/impersonation/stop",
    response_model=ImpersonationStopped,
    responses=error_responses(401, 409),
    summary="Stop viewing as a user",
)
async def admin_stop_impersonation(
    request: Request, response: Response, current: CurrentUser, admin: Admin, settings: AppSettings
) -> ImpersonationStopped:
    """Ends the view and switches back to your own session (if it is still valid)."""
    admin_token = request.cookies.get(admin_cookie_name(settings), "")
    restored = await admin.stop_impersonation(current.session, admin_token)
    clear_session_cookie(response, settings, name=admin_cookie_name(settings))
    if restored:
        set_session_cookie(response, admin_token, settings)
    else:
        clear_session_cookie(response, settings)
    return ImpersonationStopped(restored_admin_session=restored)
