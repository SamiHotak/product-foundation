"""Organization and membership queries."""

import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Membership, Organization, Role
from app.models.user import User

_ROLE_ORDER = {Role.OWNER: 0, Role.ADMIN: 1, Role.MEMBER: 2}


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

    async def get(self, organization_id: uuid.UUID) -> Organization | None:
        """One organization by id. Only for callers that already proved access (API keys)."""
        return await self._session.get(Organization, organization_id)

    # --- members --------------------------------------------------------------------------

    async def list_members(self, organization_id: uuid.UUID) -> list[tuple[Membership, User]]:
        """Everyone in the workspace: owner first, then admins, then members; oldest first."""
        rows = await self._session.execute(
            select(Membership, User)
            .join(User, User.id == Membership.user_id)
            .where(Membership.organization_id == organization_id)
            .order_by(Membership.created_at, Membership.id)
        )
        members = [(m, u) for m, u in rows.tuples()]
        return sorted(members, key=lambda mu: _ROLE_ORDER[mu[0].role])

    async def get_membership(
        self, organization_id: uuid.UUID, user_id: uuid.UUID
    ) -> tuple[Membership, User] | None:
        """One member of this workspace (with the user)."""
        row = await self._session.execute(
            select(Membership, User)
            .join(User, User.id == Membership.user_id)
            .where(Membership.organization_id == organization_id, Membership.user_id == user_id)
        )
        found = row.tuples().first()
        return (found[0], found[1]) if found else None

    async def add_member(
        self, organization_id: uuid.UUID, user_id: uuid.UUID, role: Role
    ) -> Membership:
        """Add a user to the workspace."""
        membership = Membership(organization_id=organization_id, user_id=user_id, role=role)
        self._session.add(membership)
        await self._session.flush()
        return membership

    async def remove_member(self, organization_id: uuid.UUID, user_id: uuid.UUID) -> None:
        """Remove a user from the workspace."""
        await self._session.execute(
            delete(Membership).where(
                Membership.organization_id == organization_id, Membership.user_id == user_id
            )
        )

    async def lock(self, organization_id: uuid.UUID) -> Organization | None:
        """Lock the workspace row until commit.

        Every role, ownership and membership change takes this lock first, so two admins
        clicking at the same time can't leave a workspace without an owner.
        """
        found: Organization | None = await self._session.scalar(
            select(Organization)
            .where(Organization.id == organization_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return found

    async def owned_with_others(self, user_id: uuid.UUID) -> list[Organization]:
        """Workspaces this user owns that have other members too."""
        members = (
            select(func.count())
            .select_from(Membership)
            .where(Membership.organization_id == Organization.id)
            .correlate(Organization)
            .scalar_subquery()
        )
        rows = await self._session.scalars(
            select(Organization)
            .join(Membership, Membership.organization_id == Organization.id)
            .where(Membership.user_id == user_id, Membership.role == Role.OWNER, members > 1)
            .order_by(Organization.name)
        )
        return list(rows)
