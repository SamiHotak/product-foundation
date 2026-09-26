"""Shared FastAPI dependencies: the caller, their workspace, and permission checks.

Signed-in people (browser, session cookie):
    async def endpoint(ctx: OrgCtx) -> ...                       # 401 if not signed in
    async def endpoint(ctx: Annotated[OrgContext, require(Permission.MEMBERS_INVITE)]) -> ...
                                                                  # + 403 without the permission
People OR API keys (public REST API):
    async def endpoint(caller: Annotated[Caller, allow_api_keys(Permission.JOBS_READ)]) -> ...
    An API key needs that permission as a scope; a person needs it through their role.
Always query tenant data with `ctx.organization.id` / `caller.organization.id`.
"""

from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import UnauthorizedError
from app.core.permissions import Permission
from app.core.rate_limit import RateLimiter, get_rate_limiter
from app.db.session import get_db
from app.models.session import UserSession
from app.models.user import User
from app.repositories.jobs import JobRepository
from app.repositories.sessions import SessionRepository
from app.repositories.users import UserRepository
from app.services.api_keys import ApiKeyService
from app.services.audit import AuditService, RequestMeta
from app.services.auth import AuthService
from app.services.deletion import DeletionService
from app.services.email import CeleryEmailSender, EmailSender
from app.services.exports import ExportService
from app.services.google_oauth import GoogleClient, HttpGoogleClient
from app.services.invites import InviteService
from app.services.jobs import JobService
from app.services.members import MemberService
from app.services.organizations import Caller, OrganizationService, OrgContext
from app.services.sessions import SessionService
from app.workers.dispatch import celery_dispatch

Db = Annotated[AsyncSession, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]
Limiter = Annotated[RateLimiter, Depends(get_rate_limiter)]


def client_ip(request: Request) -> str:
    """Caller IP (behind the proxy, uvicorn's --proxy-headers fills this in)."""
    return request.client.host if request.client else "unknown"


def get_request_meta(request: Request) -> RequestMeta:
    """IP and browser of this request (stored with audit events)."""
    return RequestMeta(ip=client_ip(request), user_agent=request.headers.get("user-agent"))


def get_email_sender() -> EmailSender:
    """Queues emails for the worker (overridden in tests)."""
    return CeleryEmailSender()


def get_google_client(settings: AppSettings) -> GoogleClient | None:
    """Google client, or None when Google sign-in is not configured (overridden in tests)."""
    if not settings.google_enabled:
        return None
    assert settings.google_client_id and settings.google_client_secret
    return HttpGoogleClient(
        settings.google_client_id, settings.google_client_secret.get_secret_value()
    )


def get_audit_service(
    db: Db, meta: Annotated[RequestMeta, Depends(get_request_meta)]
) -> AuditService:
    """Audit log writer for this request."""
    return AuditService(db, meta)


Audit = Annotated[AuditService, Depends(get_audit_service)]
Mailer = Annotated[EmailSender, Depends(get_email_sender)]


def get_session_service(db: Db, settings: AppSettings) -> SessionService:
    """Session service for this request."""
    return SessionService(SessionRepository(db), settings)


def get_auth_service(
    db: Db, settings: AppSettings, email_sender: Mailer, limiter: Limiter, audit: Audit
) -> AuthService:
    """Auth service for this request."""
    return AuthService(db, settings, email_sender, limiter, audit)


def get_org_service(db: Db, audit: Audit) -> OrganizationService:
    """Organization service for this request."""
    return OrganizationService(db, audit)


def get_job_service(db: Db) -> JobService:
    """Job service for this request (overridden in tests)."""
    return JobService(JobRepository(db), celery_dispatch)


Sessions = Annotated[SessionService, Depends(get_session_service)]
Auth = Annotated[AuthService, Depends(get_auth_service)]
Orgs = Annotated[OrganizationService, Depends(get_org_service)]
Jobs = Annotated[JobService, Depends(get_job_service)]


def get_member_service(db: Db, audit: Audit) -> MemberService:
    """Member service for this request."""
    return MemberService(db, audit)


def get_invite_service(
    db: Db, settings: AppSettings, email_sender: Mailer, limiter: Limiter, audit: Audit
) -> InviteService:
    """Invite service for this request."""
    return InviteService(db, settings, email_sender, limiter, audit)


def get_api_key_service(
    db: Db, settings: AppSettings, limiter: Limiter, audit: Audit
) -> ApiKeyService:
    """API key service for this request."""
    return ApiKeyService(db, settings, limiter, audit)


def get_export_service(
    db: Db, settings: AppSettings, limiter: Limiter, audit: Audit, jobs: Jobs
) -> ExportService:
    """Export service for this request."""
    return ExportService(db, settings, limiter, audit, jobs)


def get_deletion_service(
    db: Db, settings: AppSettings, email_sender: Mailer, audit: Audit
) -> DeletionService:
    """Deletion service for this request."""
    return DeletionService(db, settings, email_sender, audit)


Members = Annotated[MemberService, Depends(get_member_service)]
Invites = Annotated[InviteService, Depends(get_invite_service)]
ApiKeys = Annotated[ApiKeyService, Depends(get_api_key_service)]
Exports = Annotated[ExportService, Depends(get_export_service)]
Deletions = Annotated[DeletionService, Depends(get_deletion_service)]


# --- who is calling -----------------------------------------------------------------------


@dataclass(frozen=True)
class CurrentAuth:
    """The signed-in user and their session."""

    user: User
    session: UserSession


async def _session_auth(
    request: Request, db: AsyncSession, sessions: SessionService, settings: Settings
) -> CurrentAuth:
    token = request.cookies.get(settings.session_cookie_name, "")
    user_session = await sessions.resolve(token)
    if user_session is None:
        raise UnauthorizedError("Please sign in.")
    user = await UserRepository(db).get(user_session.user_id)
    if user is None or not user.is_active:
        raise UnauthorizedError("Please sign in.")
    if db.dirty:  # sliding expiry was extended
        await db.commit()
    return CurrentAuth(user=user, session=user_session)


async def get_current_auth(
    request: Request, db: Db, sessions: Sessions, settings: AppSettings
) -> CurrentAuth:
    """401 unless the request has a valid session cookie for an active user."""
    return await _session_auth(request, db, sessions, settings)


CurrentUser = Annotated[CurrentAuth, Depends(get_current_auth)]


async def get_org_context(current: CurrentUser, orgs: Orgs) -> OrgContext:
    """The signed-in user plus the active workspace (for all tenant data)."""
    return await orgs.resolve_context(current.user, current.session)


OrgCtx = Annotated[OrgContext, Depends(get_org_context)]


def require(permission: Permission) -> Any:
    """Dependency: the signed-in person's context, 403 unless their role allows `permission`."""

    async def check(ctx: OrgCtx) -> OrgContext:
        ctx.require(permission)
        return ctx

    return Depends(check)


def bearer_token(request: Request) -> str | None:
    """The token from `Authorization: Bearer ...`, or None."""
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    return token.strip() if scheme.lower() == "bearer" else None


async def get_caller(
    request: Request,
    db: Db,
    sessions: Sessions,
    settings: AppSettings,
    orgs: Orgs,
    keys: ApiKeys,
) -> Caller:
    """A person (session cookie) or an API key (Bearer header). Overridden in unit tests."""
    token = bearer_token(request)
    if token is not None:
        return await keys.authenticate(token)
    current = await _session_auth(request, db, sessions, settings)
    return (await orgs.resolve_context(current.user, current.session)).as_caller()


def allow_api_keys(permission: Permission) -> Any:
    """Dependency for public API endpoints: a person or an API key, allowed `permission`."""

    async def check(caller: Annotated[Caller, Depends(get_caller)]) -> Caller:
        caller.require(permission)
        return caller

    return Depends(check)


# --- cookies ------------------------------------------------------------------------------


def set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    """httpOnly (no JavaScript access), SameSite=Lax (not sent on cross-site POSTs)."""
    response.set_cookie(
        settings.session_cookie_name,
        token,
        max_age=settings.session_days * 24 * 3600,
        httponly=True,
        secure=bool(settings.session_cookie_secure),
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response, settings: Settings) -> None:
    """Remove the cookie in the browser."""
    response.delete_cookie(
        settings.session_cookie_name,
        httponly=True,
        secure=bool(settings.session_cookie_secure),
        samesite="lax",
        path="/",
    )
