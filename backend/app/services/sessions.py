"""Login sessions: create, look up (sliding expiry), end."""

import uuid
from datetime import UTC, datetime, timedelta

from app.core.config import Settings
from app.core.security import hash_token, new_token
from app.models.session import UserSession
from app.repositories.sessions import SessionRepository

# Don't write to the database on every request: refresh last_seen/expiry at most this often.
TOUCH_EVERY = timedelta(minutes=5)


def utcnow() -> datetime:
    """Current time (UTC, timezone-aware)."""
    return datetime.now(UTC)


class SessionService:
    """Server-side sessions. The cookie holds a random token; the database its hash."""

    def __init__(self, repo: SessionRepository, settings: Settings) -> None:
        self._repo = repo
        self._lifetime = timedelta(days=settings.session_days)

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        organization_id: uuid.UUID | None,
        ip: str | None,
        user_agent: str | None,
    ) -> tuple[str, UserSession]:
        """Start a session. Returns (cookie token, session). Always a NEW token (no fixation)."""
        token = new_token()
        now = utcnow()
        user_session = await self._repo.add(
            UserSession(
                token_hash=hash_token(token),
                user_id=user_id,
                active_organization_id=organization_id,
                expires_at=now + self._lifetime,
                last_seen_at=now,
                ip_address=(ip or "")[:64] or None,
                user_agent=(user_agent or "")[:300] or None,
            )
        )
        return token, user_session

    async def resolve(self, token: str) -> UserSession | None:
        """The session for a cookie token, or None. Extends the expiry while in use."""
        if not token or len(token) > 200:
            return None
        now = utcnow()
        user_session = await self._repo.get_valid(hash_token(token), now)
        if user_session is not None and now - user_session.last_seen_at > TOUCH_EVERY:
            user_session.last_seen_at = now
            user_session.expires_at = now + self._lifetime
        return user_session

    async def commit(self) -> None:
        """Save the new or changed session."""
        await self._repo.commit()

    async def end(self, user_session: UserSession) -> None:
        """Sign out this browser."""
        await self._repo.delete(user_session.id)

    async def end_all(self, user_id: uuid.UUID) -> None:
        """Sign out everywhere."""
        await self._repo.delete_all_for_user(user_id)
