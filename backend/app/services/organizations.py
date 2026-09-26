"""Workspaces: list, create, and resolve which one the current request works in."""

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.models.organization import Membership, Organization
from app.models.session import UserSession
from app.models.user import User
from app.repositories.organizations import OrganizationRepository
from app.schemas.auth import MeResponse, OrganizationRead, UserRead
from app.services.auth import workspace_name


@dataclass(frozen=True)
class OrgContext:
    """Who is asking, and in which workspace. Every tenant query uses `organization.id`."""

    user: User
    session: UserSession
    organization: Organization
    membership: Membership


class OrganizationService:
    """Organization operations for the signed-in user."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._repo = OrganizationRepository(db)

    async def resolve_context(self, user: User, user_session: UserSession) -> OrgContext:
        """The active workspace for this session (falls back to the first one).

        If the user belongs to no workspace (e.g. removed everywhere), a personal one is created.
        """
        if user_session.active_organization_id is not None:
            found = await self._repo.get_for_user(user_session.active_organization_id, user.id)
            if found is not None:
                return OrgContext(user, user_session, found[0], found[1])
        orgs = await self._repo.list_for_user(user.id)
        if not orgs:
            await self._repo.create(name=workspace_name(user.name), owner_id=user.id)
            orgs = await self._repo.list_for_user(user.id)
        org, membership = orgs[0]
        user_session.active_organization_id = org.id
        await self._db.commit()
        return OrgContext(user, user_session, org, membership)

    async def list_for_user(self, user: User) -> list[OrganizationRead]:
        """The user's workspaces with roles."""
        return [
            OrganizationRead(id=org.id, name=org.name, role=m.role)
            for org, m in await self._repo.list_for_user(user.id)
        ]

    async def create(self, user: User, user_session: UserSession, name: str) -> OrganizationRead:
        """New workspace owned by the user; it becomes the active one."""
        org = await self._repo.create(name=name.strip(), owner_id=user.id)
        user_session.active_organization_id = org.id
        await self._db.commit()
        found = await self._repo.get_for_user(org.id, user.id)
        assert found is not None
        return OrganizationRead(id=org.id, name=org.name, role=found[1].role)

    async def switch(
        self, user: User, user_session: UserSession, organization_id: uuid.UUID
    ) -> None:
        """Make another workspace active. Only works for the user's own workspaces."""
        if await self._repo.get_for_user(organization_id, user.id) is None:
            raise NotFoundError("This workspace does not exist.")
        user_session.active_organization_id = organization_id
        await self._db.commit()

    async def me(self, user: User, user_session: UserSession) -> MeResponse:
        """The "who am I" payload for the app."""
        context = await self.resolve_context(user, user_session)
        return MeResponse(
            user=UserRead(
                id=user.id,
                email=user.email,
                name=user.name,
                email_verified=user.is_verified,
                has_password=user.password_hash is not None,
                google_linked=user.google_sub is not None,
                created_at=user.created_at,
            ),
            organizations=await self.list_for_user(user),
            active_organization_id=context.organization.id,
        )
