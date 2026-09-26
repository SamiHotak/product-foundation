"""Login session queries."""

import uuid
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.session import UserSession


class SessionRepository:
    """Sessions are looked up by the SHA-256 hash of the cookie token."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, user_session: UserSession) -> UserSession:
        """Insert a session."""
        self._session.add(user_session)
        await self._session.flush()
        return user_session

    async def get_valid(self, token_hash: str, now: datetime) -> UserSession | None:
        """A session that exists and has not expired."""
        found: UserSession | None = await self._session.scalar(
            select(UserSession).where(
                UserSession.token_hash == token_hash, UserSession.expires_at > now
            )
        )
        return found

    async def delete(self, session_id: uuid.UUID) -> None:
        """Sign out one browser."""
        await self._session.execute(delete(UserSession).where(UserSession.id == session_id))

    async def commit(self) -> None:
        """Commit the current transaction."""
        await self._session.commit()

    async def delete_all_for_user(self, user_id: uuid.UUID) -> None:
        """Sign out everywhere (after a password reset)."""
        await self._session.execute(delete(UserSession).where(UserSession.user_id == user_id))
