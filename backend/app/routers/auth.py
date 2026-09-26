"""Auth endpoints. Thin: rate-limit, call AuthService, manage the session cookie."""

import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import RedirectResponse

from app.core.config import Settings
from app.core.errors import RateLimitedError
from app.core.logging import get_logger
from app.core.rate_limit import RateLimiter, get_rate_limiter
from app.models.user import User
from app.routers.deps import (
    AppSettings,
    Auth,
    CurrentUser,
    Db,
    Orgs,
    Sessions,
    clear_session_cookie,
    client_ip,
    get_google_client,
    set_session_cookie,
)
from app.schemas.auth import (
    AuthProviders,
    EmailRequest,
    LoginRequest,
    MeResponse,
    MessageResponse,
    ResetPasswordRequest,
    SignupRequest,
    SwitchOrganization,
    TokenRequest,
)
from app.schemas.errors import error_responses
from app.services.auth import GoogleSignInError
from app.services.google_oauth import GoogleAuthError, GoogleClient, new_pkce_pair
from app.services.organizations import OrganizationService
from app.services.sessions import SessionService

logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

CHECK_EMAIL = "If the details are right, we sent you an email. Check your inbox (and spam folder)."
GOOGLE_COOKIE = "google_oauth"


async def limit_per_ip(
    request: Request,
    settings: AppSettings,
    limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
) -> None:
    """Brute-force protection: at most N auth requests per minute per IP."""
    wait = await limiter.hit(
        f"auth-ip:{client_ip(request)}",
        limit=settings.auth_requests_per_minute_per_ip,
        window_seconds=60,
    )
    if wait is not None:
        raise RateLimitedError("Too many requests. Wait a minute and try again.", retry_after=wait)


RateLimited = [Depends(limit_per_ip)]


async def _start_session(
    request: Request,
    response: Response,
    user: User,
    sessions: SessionService,
    orgs: OrganizationService,
    settings: Settings,
) -> MeResponse:
    token, user_session = await sessions.create(
        user_id=user.id,
        organization_id=None,
        ip=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    me = await orgs.me(user, user_session)  # commits (sets the active workspace)
    set_session_cookie(response, token, settings)
    return me


@router.get("/providers", response_model=AuthProviders, summary="Sign-in options")
async def providers(settings: AppSettings) -> AuthProviders:
    """Which buttons the login page should show."""
    return AuthProviders(google=settings.google_enabled)


@router.post(
    "/signup",
    response_model=MessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=RateLimited,
    responses=error_responses(429),
    summary="Create an account",
)
async def signup(data: SignupRequest, auth: Auth) -> MessageResponse:
    """Always answers the same, so nobody can learn which emails are registered."""
    await auth.signup(name=data.name, email=str(data.email), password=data.password)
    return MessageResponse(message=CHECK_EMAIL)


@router.post(
    "/resend-verification",
    response_model=MessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=RateLimited,
    responses=error_responses(429),
    summary="Send a new verification email",
)
async def resend_verification(data: EmailRequest, auth: Auth) -> MessageResponse:
    """Same answer whether or not the account exists."""
    await auth.resend_verification(str(data.email))
    return MessageResponse(message=CHECK_EMAIL)


@router.post(
    "/verify-email",
    response_model=MeResponse,
    dependencies=RateLimited,
    responses=error_responses(400, 429),
    summary="Confirm the email address (signs in)",
)
async def verify_email(
    data: TokenRequest,
    request: Request,
    response: Response,
    auth: Auth,
    sessions: Sessions,
    orgs: Orgs,
    settings: AppSettings,
) -> MeResponse:
    """Uses the token from the email link, then starts a session."""
    user = await auth.verify_email(data.token)
    return await _start_session(request, response, user, sessions, orgs, settings)


@router.post(
    "/login",
    response_model=MeResponse,
    dependencies=RateLimited,
    responses=error_responses(401, 403, 429),
    summary="Sign in with email and password",
)
async def login(
    data: LoginRequest,
    request: Request,
    response: Response,
    auth: Auth,
    sessions: Sessions,
    orgs: Orgs,
    settings: AppSettings,
) -> MeResponse:
    """Starts a new session (a new cookie every time)."""
    user = await auth.login(email=str(data.email), password=data.password)
    return await _start_session(request, response, user, sessions, orgs, settings)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Sign out")
async def logout(request: Request, db: Db, sessions: Sessions, settings: AppSettings) -> Response:
    """Ends this browser's session. Works even if already signed out."""
    user_session = await sessions.resolve(request.cookies.get(settings.session_cookie_name, ""))
    if user_session is not None:
        await sessions.end(user_session)
        await db.commit()
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session_cookie(response, settings)
    return response


@router.post(
    "/forgot-password",
    response_model=MessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=RateLimited,
    responses=error_responses(429),
    summary="Email a password reset link",
)
async def forgot_password(data: EmailRequest, auth: Auth) -> MessageResponse:
    """Same answer whether or not the account exists."""
    await auth.forgot_password(str(data.email))
    return MessageResponse(message=CHECK_EMAIL)


@router.post(
    "/reset-password",
    response_model=MeResponse,
    dependencies=RateLimited,
    responses=error_responses(400, 429),
    summary="Set a new password (signs out everywhere, then signs in)",
)
async def reset_password(
    data: ResetPasswordRequest,
    request: Request,
    response: Response,
    auth: Auth,
    sessions: Sessions,
    orgs: Orgs,
    settings: AppSettings,
) -> MeResponse:
    """Old sessions end: if someone else was signed in, they are out now."""
    user = await auth.reset_password(token=data.token, password=data.password)
    await sessions.end_all(user.id)
    return await _start_session(request, response, user, sessions, orgs, settings)


@router.get("/me", response_model=MeResponse, responses=error_responses(401), summary="Who am I")
async def me(current: CurrentUser, orgs: Orgs) -> MeResponse:
    """The signed-in user, their workspaces and the active one."""
    return await orgs.me(current.user, current.session)


@router.put(
    "/session/organization",
    response_model=MeResponse,
    responses=error_responses(401, 404),
    summary="Switch workspace",
)
async def switch_organization(
    data: SwitchOrganization, current: CurrentUser, orgs: Orgs
) -> MeResponse:
    """Only your own workspaces; others look like they don't exist (404)."""
    await orgs.switch(current.user, current.session, data.organization_id)
    return await orgs.me(current.user, current.session)


# --- Google ------------------------------------------------------------------------------


def _google_redirect_uri(settings: Settings) -> str:
    return f"{settings.app_url}/api/auth/google/callback"


@router.get("/google/start", include_in_schema=False, dependencies=RateLimited)
async def google_start(
    settings: AppSettings,
    google: Annotated[GoogleClient | None, Depends(get_google_client)],
) -> RedirectResponse:
    """Send the browser to Google's account chooser."""
    if google is None:
        return RedirectResponse(
            "/login?error=google_disabled", status_code=status.HTTP_303_SEE_OTHER
        )
    state = secrets.token_urlsafe(24)
    verifier, challenge = new_pkce_pair()
    url = google.authorize_url(
        state=state, code_challenge=challenge, redirect_uri=_google_redirect_uri(settings)
    )
    response = RedirectResponse(url, status_code=status.HTTP_303_SEE_OTHER)
    # httpOnly + short-lived: only this browser can finish the flow it started.
    response.set_cookie(
        GOOGLE_COOKIE,
        f"{state}.{verifier}",
        max_age=600,
        httponly=True,
        secure=bool(settings.session_cookie_secure),
        samesite="lax",
        path="/api/auth/google",
    )
    return response


@router.get("/google/callback", include_in_schema=False, dependencies=RateLimited)
async def google_callback(
    request: Request,
    auth: Auth,
    sessions: Sessions,
    orgs: Orgs,
    settings: AppSettings,
    google: Annotated[GoogleClient | None, Depends(get_google_client)],
    code: Annotated[str | None, Query(max_length=2000)] = None,
    state: Annotated[str | None, Query(max_length=200)] = None,
) -> RedirectResponse:
    """Finish Google sign-in, then go to the dashboard (or back to login with an error)."""
    failed = RedirectResponse("/login?error=google", status_code=status.HTTP_303_SEE_OTHER)
    failed.delete_cookie(GOOGLE_COOKIE, path="/api/auth/google")
    saved_state, _, verifier = request.cookies.get(GOOGLE_COOKIE, "").partition(".")
    if google is None or not code or not state or not saved_state or not verifier:
        return failed
    if not secrets.compare_digest(state, saved_state):
        logger.warning("google_state_mismatch")
        return failed
    try:
        profile = await google.fetch_profile(
            code=code, code_verifier=verifier, redirect_uri=_google_redirect_uri(settings)
        )
        user, end_others = await auth.google_sign_in(profile)
    except (GoogleAuthError, GoogleSignInError) as exc:
        logger.warning("google_sign_in_failed", error=str(exc)[:200])
        return failed
    if end_others:
        await sessions.end_all(user.id)
    response = RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    await _start_session(request, response, user, sessions, orgs, settings)
    response.delete_cookie(GOOGLE_COOKIE, path="/api/auth/google")
    return response
