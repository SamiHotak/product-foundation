"""Organization and membership queries."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Membership, Organization, Role


class OrganizationRepository:
    """Organizations are only ever read through a membership of the current user."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, *, name: str, owner_id: uuid.UUID) -> Organization:
        """Create an organization with its owner."""
        org = Organization(name=name)
        self._session.add(org)
        await self._session.flush()
        self._session.add(Membership(organization_id=org.id, user_id=owner_id, role=Role.OWNER))
        await self._session.flush()
        return org

    async def list_for_user(self, user_id: uuid.UUID) -> list[tuple[Organization, Membership]]:
        """The user's organizations with their role, oldest first."""
        rows = await self._session.execute(
            select(Organization, Membership)
            .join(Membership, Membership.organization_id == Organization.id)
            .where(Membership.user_id == user_id)
            .order_by(Membership.created_at, Organization.id)
        )
        return [(org, membership) for org, membership in rows.tuples()]

    async def get_for_user(
        self, organization_id: uuid.UUID, user_id: uuid.UUID
    ) -> tuple[Organization, Membership] | None:
        """One organization, only if the user is a member of it."""
        row = await self._session.execute(
            select(Organization, Membership)
            .join(Membership, Membership.organization_id == Organization.id)
            .where(Organization.id == organization_id, Membership.user_id == user_id)
        )
        found = row.tuples().first()
        return (found[0], found[1]) if found else None
