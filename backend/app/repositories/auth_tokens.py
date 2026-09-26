"""Email verification / password reset token queries."""

import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth_token import AuthToken, TokenPurpose


class AuthTokenRepository:
    """Single-use tokens, stored as hashes."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, token: AuthToken) -> AuthToken:
        """Insert a token."""
        self._session.add(token)
        await self._session.flush()
        return token

    async def get_usable(
        self, token_hash: str, purpose: TokenPurpose, now: datetime
    ) -> AuthToken | None:
        """A token that matches, is unused and not expired. Locks the row."""
        found: AuthToken | None = await self._session.scalar(
            select(AuthToken)
            .where(
                AuthToken.token_hash == token_hash,
                AuthToken.purpose == purpose,
                AuthToken.used_at.is_(None),
                AuthToken.expires_at > now,
            )
            .with_for_update()
        )
        return found

    async def invalidate_all(
        self, user_id: uuid.UUID, purpose: TokenPurpose, now: datetime
    ) -> None:
        """Mark every open token of this kind as used (only the newest link works)."""
        await self._session.execute(
            update(AuthToken)
            .where(
                AuthToken.user_id == user_id,
                AuthToken.purpose == purpose,
                AuthToken.used_at.is_(None),
            )
            .values(used_at=now)
        )
