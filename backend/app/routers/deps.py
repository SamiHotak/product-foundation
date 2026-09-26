"""Shared FastAPI dependencies: the signed-in user and the active workspace.

Use them in routers:
    async def endpoint(ctx: OrgCtx) -> ...:   # 401 if not signed in
        ...query with ctx.organization.id...
"""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import UnauthorizedError
from app.core.rate_limit import RateLimiter, get_rate_limiter
from app.db.session import get_db
from app.models.session import UserSession
from app.models.user import User
from app.repositories.sessions import SessionRepository
from app.repositories.users import UserRepository
from app.services.auth import AuthService
from app.services.email import CeleryEmailSender, EmailSender
from app.services.google_oauth import GoogleClient, HttpGoogleClient
from app.services.organizations import OrganizationService, OrgContext
from app.services.sessions import SessionService

Db = Annotated[AsyncSession, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]


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


def get_session_service(db: Db, settings: AppSettings) -> SessionService:
    """Session service for this request."""
    return SessionService(SessionRepository(db), settings)


def get_auth_service(
    db: Db,
    settings: AppSettings,
    email_sender: Annotated[EmailSender, Depends(get_email_sender)],
    limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
) -> AuthService:
    """Auth service for this request."""
    return AuthService(db, settings, email_sender, limiter)


def get_org_service(db: Db) -> OrganizationService:
    """Organization service for this request."""
    return OrganizationService(db)


Sessions = Annotated[SessionService, Depends(get_session_service)]
Auth = Annotated[AuthService, Depends(get_auth_service)]
Orgs = Annotated[OrganizationService, Depends(get_org_service)]


@dataclass(frozen=True)
class CurrentAuth:
    """The signed-in user and their session."""

    user: User
    session: UserSession


async def get_current_auth(
    request: Request, db: Db, sessions: Sessions, settings: AppSettings
) -> CurrentAuth:
    """401 unless the request has a valid session cookie for an active user."""
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


CurrentUser = Annotated[CurrentAuth, Depends(get_current_auth)]


async def get_org_context(current: CurrentUser, orgs: Orgs) -> OrgContext:
    """The signed-in user plus the active workspace (for all tenant data)."""
    return await orgs.resolve_context(current.user, current.session)


OrgCtx = Annotated[OrgContext, Depends(get_org_context)]


def client_ip(request: Request) -> str:
    """Caller IP (behind the proxy, uvicorn's --proxy-headers fills this in)."""
    return request.client.host if request.client else "unknown"


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
