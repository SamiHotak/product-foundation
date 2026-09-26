"""API key queries. Workspace-side queries always take the organization id."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api_key import ApiKey
from app.models.user import User


class ApiKeyRepository:
    """API keys of a workspace, and lookup by hash for authentication."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, key: ApiKey) -> ApiKey:
        """Insert a key."""
        self._session.add(key)
        await self._session.flush()
        return key

    async def list_active(self, organization_id: uuid.UUID) -> list[tuple[ApiKey, User | None]]:
        """Keys that are not revoked (expired ones are listed, marked expired), newest first."""
        rows = await self._session.execute(
            select(ApiKey, User)
            .outerjoin(User, User.id == ApiKey.created_by_id)
            .where(ApiKey.organization_id == organization_id, ApiKey.revoked_at.is_(None))
            .order_by(ApiKey.created_at.desc(), ApiKey.id)
        )
        return [(k, u) for k, u in rows.tuples()]

    async def get(self, key_id: uuid.UUID, *, organization_id: uuid.UUID) -> ApiKey | None:
        """One key of this workspace."""
        found: ApiKey | None = await self._session.scalar(
            select(ApiKey).where(ApiKey.id == key_id, ApiKey.organization_id == organization_id)
        )
        return found

    async def get_by_hash(self, key_hash: str) -> ApiKey | None:
        """The key with this hash (for authenticating API requests)."""
        found: ApiKey | None = await self._session.scalar(
            select(ApiKey).where(ApiKey.key_hash == key_hash)
        )
        return found
