"""User queries."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


class UserRepository:
    """Users are global (not tenant data); organization access goes through memberships."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: uuid.UUID) -> User | None:
        """One user by id."""
        return await self._session.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        """One user by email (case-insensitive: the column is CITEXT)."""
        found: User | None = await self._session.scalar(
            select(User).where(User.email == email.strip())
        )
        return found

    async def get_by_google_sub(self, sub: str) -> User | None:
        """One user by their Google account id."""
        found: User | None = await self._session.scalar(select(User).where(User.google_sub == sub))
        return found

    async def add(self, user: User) -> User:
        """Insert a user."""
        self._session.add(user)
        await self._session.flush()
        return user
