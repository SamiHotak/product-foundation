"""The signed-in person's own account: profile and password.

Security rules used here:
- Changing a password needs the current one (Google-only accounts set their first one).
- Wrong current passwords are counted; after `login_max_failures` the change is locked for
  `login_lock_minutes` (same limits as sign-in, so this is no easier way to guess).
- After a password change every OTHER browser is signed out; this one stays signed in.
"""

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError, RateLimitedError
from app.core.logging import get_logger
from app.core.rate_limit import RateLimiter
from app.core.security import hash_password, verify_password
from app.models.session import UserSession
from app.models.user import User
from app.repositories.sessions import SessionRepository
from app.services.audit import AuditAction, AuditService

logger = get_logger(__name__)


class WrongPasswordError(AppError):
    """The current password does not match."""

    status_code = status.HTTP_400_BAD_REQUEST
    code = "wrong_password"


class AccountService:
    """Profile and password of the signed-in person."""

    def __init__(
        self, db: AsyncSession, settings: Settings, limiter: RateLimiter, audit: AuditService
    ) -> None:
        self._db = db
        self._settings = settings
        self._limiter = limiter
        self._audit = audit
        self._sessions = SessionRepository(db)

    async def update_profile(self, user: User, *, name: str) -> User:
        """Change the display name (shown to the team, in emails and in the audit log)."""
        if name != user.name:
            await self._audit.record(
                AuditAction.ACCOUNT_PROFILE_UPDATED,
                organization_id=None,
                actor_user_id=user.id,
                target_type="user",
                target_id=user.id,
                details={"fields": ["name"]},
            )
            user.name = name
            await self._db.commit()
            logger.info("profile_updated", user_id=str(user.id))
        return user

    async def change_password(
        self,
        user: User,
        current_session: UserSession,
        *,
        current_password: str | None,
        new_password: str,
    ) -> User:
        """Set a new password and sign out every other browser."""
        key = f"password-change-fail:{user.id}"
        if user.password_hash is not None:
            failures, remaining = await self._limiter.count(key)
            if failures >= self._settings.login_max_failures:
                raise RateLimitedError(
                    "Too many wrong passwords. Wait a few minutes and try again.",
                    retry_after=max(remaining, 1),
                )
            if not current_password or not verify_password(current_password, user.password_hash):
                await self._limiter.hit(
                    key,
                    limit=self._settings.login_max_failures,
                    window_seconds=self._settings.login_lock_minutes * 60,
                )
                raise WrongPasswordError("Your current password is not right.")
            await self._limiter.reset(key)
        first_password = user.password_hash is None
        user.password_hash = hash_password(new_password)
        await self._sessions.delete_others_for_user(user.id, current_session.id)
        await self._audit.record(
            AuditAction.AUTH_PASSWORD_CHANGED,
            organization_id=None,
            actor_user_id=user.id,
            target_type="user",
            target_id=user.id,
            details={"first_password": first_password},
        )
        await self._db.commit()
        logger.info("password_changed", user_id=str(user.id), first=first_password)
        return user
