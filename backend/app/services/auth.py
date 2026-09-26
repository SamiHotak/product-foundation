"""Sign-up, email verification, login, password reset and Google sign-in.

Security rules used here:
- Responses never reveal whether an email is registered (sign-up, resend, forgot password
  always answer "check your email").
- Login failures are counted per email; after `login_max_failures` the email is locked for
  `login_lock_minutes`. Every auth request is also limited per IP (see the router).
- Email tokens are single-use, expire, and are stored as hashes. A new link cancels old ones.
- A password reset signs the user out everywhere.
- Google can only link to an account when Google says the email is verified. If the existing
  account was never verified, its password is removed (stops account "pre-hijacking").
"""

from datetime import timedelta

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError, RateLimitedError, UnauthorizedError
from app.core.logging import get_logger
from app.core.rate_limit import RateLimiter
from app.core.security import (
    hash_password,
    hash_token,
    new_token,
    password_needs_rehash,
    verify_password,
)
from app.models.auth_token import AuthToken, TokenPurpose
from app.models.organization import Organization
from app.models.user import User
from app.repositories.auth_tokens import AuthTokenRepository
from app.repositories.organizations import OrganizationRepository
from app.repositories.users import UserRepository
from app.services import email as emails
from app.services.audit import AuditAction, AuditService
from app.services.email import EmailSender
from app.services.google_oauth import GoogleProfile
from app.services.organizations import workspace_name
from app.services.sessions import utcnow

logger = get_logger(__name__)

# How many emails one address may receive from sign-up / resend / reset per hour.
EMAILS_PER_ADDRESS_PER_HOUR = 5


class InvalidCredentialsError(AppError):
    """Wrong email or password (deliberately vague)."""

    status_code = status.HTTP_401_UNAUTHORIZED
    code = "invalid_credentials"


class EmailNotVerifiedError(AppError):
    """Right password, but the email is not confirmed yet."""

    status_code = status.HTTP_403_FORBIDDEN
    code = "email_not_verified"


class InvalidTokenError(AppError):
    """The email link is wrong, used or expired."""

    status_code = status.HTTP_400_BAD_REQUEST
    code = "invalid_token"


class GoogleSignInError(AppError):
    """Google sign-in can't be completed."""

    status_code = status.HTTP_400_BAD_REQUEST
    code = "google_sign_in_failed"


def _email_key(email: str) -> str:
    return email.strip().lower()


class AuthService:
    """All account flows. Routers turn the returned users into sessions."""

    def __init__(
        self,
        db: AsyncSession,
        settings: Settings,
        email_sender: EmailSender,
        limiter: RateLimiter,
        audit: AuditService,
    ) -> None:
        self._db = db
        self._settings = settings
        self._email = email_sender
        self._limiter = limiter
        self._audit = audit
        self.users = UserRepository(db)
        self.orgs = OrganizationRepository(db)
        self.tokens = AuthTokenRepository(db)

    # --- helpers -------------------------------------------------------------------------

    def _url(self, path: str) -> str:
        return f"{self._settings.app_url}{path}"

    async def _may_email(self, email: str) -> bool:
        """Stop anyone from flooding an inbox through our forms."""
        wait = await self._limiter.hit(
            f"email-send:{_email_key(email)}",
            limit=EMAILS_PER_ADDRESS_PER_HOUR,
            window_seconds=3600,
        )
        if wait is not None:
            logger.warning("email_rate_limited")
        return wait is None

    async def _issue_token(self, user: User, purpose: TokenPurpose, lifetime: timedelta) -> str:
        now = utcnow()
        await self.tokens.invalidate_all(user.id, purpose, now)
        token = new_token()
        await self.tokens.add(
            AuthToken(
                token_hash=hash_token(token),
                user_id=user.id,
                purpose=purpose,
                expires_at=now + lifetime,
            )
        )
        return token

    async def _consume_token(self, token: str, purpose: TokenPurpose) -> User:
        now = utcnow()
        row = await self.tokens.get_usable(hash_token(token), purpose, now)
        user = await self.users.get(row.user_id) if row else None
        if row is None or user is None or not user.is_active:
            raise InvalidTokenError("This link is invalid or has expired. Ask for a new one.")
        row.used_at = now
        return user

    async def _send_verification(self, user: User) -> None:
        token = await self._issue_token(
            user,
            TokenPurpose.VERIFY_EMAIL,
            timedelta(hours=self._settings.email_verification_hours),
        )
        await self._db.commit()
        await self._email.send(
            emails.verification_email(
                to=user.email,
                name=user.name,
                url=self._url(f"/verify-email?token={token}"),
                app_name=self._settings.app_name,
                hours=self._settings.email_verification_hours,
            )
        )

    async def _create_user_with_workspace(self, user: User) -> Organization:
        await self.users.add(user)
        org = await self.orgs.create(name=workspace_name(user.name), owner_id=user.id)
        await self._audit.record(
            AuditAction.ORG_CREATED,
            organization_id=org.id,
            actor_user_id=user.id,
            details={"name": org.name},
        )
        return org

    async def _record_login(self, user: User, method: str) -> None:
        """An account event (no workspace): part of the user's own data export."""
        await self._audit.record(
            AuditAction.AUTH_LOGIN,
            organization_id=None,
            actor_user_id=user.id,
            details={"method": method},
        )

    # --- flows ---------------------------------------------------------------------------

    async def signup(self, *, name: str, email: str, password: str) -> None:
        """Create an account (or re-send the right email). Always looks the same to callers."""
        existing = await self.users.get_by_email(email)
        if existing is not None and existing.is_verified:
            if await self._may_email(email):
                await self._email.send(
                    emails.account_exists_email(
                        to=existing.email,
                        name=existing.name,
                        login_url=self._url("/login"),
                        reset_url=self._url("/forgot-password"),
                        app_name=self._settings.app_name,
                    )
                )
            return
        if existing is not None:
            # Never confirmed: whoever confirms the inbox owns it, with the newest password.
            existing.name = name
            existing.password_hash = hash_password(password)
            user = existing
        else:
            user = User(name=name, email=email.strip(), password_hash=hash_password(password))
            await self._create_user_with_workspace(user)
        await self._db.commit()
        if await self._may_email(email):
            await self._send_verification(user)
        logger.info("signup", user_id=str(user.id), new=existing is None)

    async def resend_verification(self, email: str) -> None:
        """Send a new verification link if the account exists and is not verified."""
        user = await self.users.get_by_email(email)
        if user is None or user.is_verified or not user.is_active:
            return
        if await self._may_email(email):
            await self._send_verification(user)

    async def verify_email(self, token: str) -> User:
        """Confirm the email address. The caller signs the user in."""
        user = await self._consume_token(token, TokenPurpose.VERIFY_EMAIL)
        if user.email_verified_at is None:
            user.email_verified_at = utcnow()
        user.last_login_at = utcnow()
        await self._record_login(user, "email_link")
        await self._db.commit()
        logger.info("email_verified", user_id=str(user.id))
        return user

    async def login(self, *, email: str, password: str) -> User:
        """Check the password, with a lock after too many failures."""
        key = f"login-fail:{_email_key(email)}"
        failures, remaining = await self._limiter.count(key)
        if failures >= self._settings.login_max_failures:
            raise RateLimitedError(
                "Too many failed sign-in attempts. Wait a few minutes, or reset your password.",
                retry_after=max(remaining, 1),
            )
        user = await self.users.get_by_email(email)
        # verify_password runs a dummy check when there is no user (same timing).
        valid = verify_password(password, user.password_hash if user else None)
        if not valid or user is None or not user.is_active:
            await self._limiter.hit(
                key,
                limit=self._settings.login_max_failures,
                window_seconds=self._settings.login_lock_minutes * 60,
            )
            logger.info("login_failed")
            raise InvalidCredentialsError("Email or password is wrong.")
        await self._limiter.reset(key)
        if not user.is_verified:
            raise EmailNotVerifiedError("Confirm your email first. We can send you a new link.")
        if user.password_hash and password_needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)
        user.last_login_at = utcnow()
        await self._record_login(user, "password")
        await self._db.commit()
        logger.info("login", user_id=str(user.id))
        return user

    async def forgot_password(self, email: str) -> None:
        """Email a reset link if the account exists. Same answer either way."""
        user = await self.users.get_by_email(email)
        if user is None or not user.is_active or not await self._may_email(email):
            return
        minutes = self._settings.password_reset_minutes
        token = await self._issue_token(
            user, TokenPurpose.RESET_PASSWORD, timedelta(minutes=minutes)
        )
        await self._db.commit()
        await self._email.send(
            emails.password_reset_email(
                to=user.email,
                name=user.name,
                url=self._url(f"/reset-password?token={token}"),
                app_name=self._settings.app_name,
                minutes=minutes,
            )
        )

    async def reset_password(self, *, token: str, password: str) -> User:
        """Set a new password. The caller ends all old sessions and starts a new one."""
        user = await self._consume_token(token, TokenPurpose.RESET_PASSWORD)
        user.password_hash = hash_password(password)
        # Opening the email link proves the inbox belongs to them.
        if user.email_verified_at is None:
            user.email_verified_at = utcnow()
        user.last_login_at = utcnow()
        await self._limiter.reset(f"login-fail:{_email_key(user.email)}")
        await self._audit.record(
            AuditAction.AUTH_PASSWORD_RESET, organization_id=None, actor_user_id=user.id
        )
        await self._db.commit()
        logger.info("password_reset", user_id=str(user.id))
        return user

    async def google_sign_in(self, profile: GoogleProfile) -> tuple[User, bool]:
        """Find, link or create the account. Returns (user, whether other sessions must end)."""
        if not profile.email_verified:
            raise GoogleSignInError("Your Google account's email is not verified.")
        end_other_sessions = False
        user = await self.users.get_by_google_sub(profile.sub)
        if user is None:
            user = await self.users.get_by_email(profile.email)
            if user is not None:
                if not user.is_verified:
                    # Someone may have registered this email without owning it: drop their password.
                    user.password_hash = None
                    end_other_sessions = True
                user.google_sub = profile.sub
            else:
                user = User(
                    name=profile.name[:120],
                    email=profile.email,
                    google_sub=profile.sub,
                    password_hash=None,
                )
                await self._create_user_with_workspace(user)
        if not user.is_active:
            raise GoogleSignInError("This account is disabled.")
        if user.email_verified_at is None:
            user.email_verified_at = utcnow()
        user.last_login_at = utcnow()
        await self._record_login(user, "google")
        await self._db.commit()
        logger.info("google_login", user_id=str(user.id))
        return user, end_other_sessions


__all__ = [
    "AuthService",
    "EmailNotVerifiedError",
    "GoogleSignInError",
    "InvalidCredentialsError",
    "InvalidTokenError",
    "UnauthorizedError",
    "workspace_name",
]
