"""Workspaces: who is asking, what they may do, and workspace-level settings.

Two kinds of callers:
- `OrgContext`: a signed-in person in their active workspace (browser, session cookie).
- `Caller`: a person OR an API key. Endpoints of the public REST API use this one.
Both answer `can(permission)` with the rules from app/core/permissions.py.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, PermissionDeniedError
from app.core.permissions import Permission, role_permissions
from app.models.api_key import ApiKey
from app.models.organization import Membership, Organization
from app.models.session import UserSession
from app.models.user import User
from app.repositories.organizations import OrganizationRepository
from app.schemas.auth import MeResponse, OrganizationRead, UserRead
from app.services.audit import AuditAction, AuditService

NOT_ALLOWED = "You don't have permission to do this. Ask an owner or admin of this workspace."


def workspace_name(name: str) -> str:
    """Default name for the first workspace: "Ezat's workspace"."""
    first = name.split()[0] if name.split() else "My"
    return f"{first}'s workspace"[:80]


@dataclass(frozen=True)
class Caller:
    """Who is calling (a person or an API key), in which workspace, allowed to do what."""

    organization: Organization
    permissions: frozenset[Permission]
    user: User | None = None
    api_key: ApiKey | None = None

    def can(self, permission: Permission) -> bool:
        """True if allowed."""
        return permission in self.permissions

    def require(self, permission: Permission) -> None:
        """Raise 403 unless allowed."""
        if not self.can(permission):
            raise PermissionDeniedError(NOT_ALLOWED)

    @property
    def user_id(self) -> uuid.UUID | None:
        """The person, if a person is calling."""
        return self.user.id if self.user else None

    @property
    def api_key_id(self) -> uuid.UUID | None:
        """The API key, if a key is calling."""
        return self.api_key.id if self.api_key else None


@dataclass(frozen=True)
class OrgContext:
    """A signed-in person in their active workspace. Every tenant query uses `organization.id`."""

    user: User
    session: UserSession
    organization: Organization
    membership: Membership

    @property
    def permissions(self) -> frozenset[Permission]:
        """What this person may do here (from their role)."""
        return role_permissions(self.membership.role.value)

    def can(self, permission: Permission) -> bool:
        """True if allowed."""
        return permission in self.permissions

    def require(self, permission: Permission) -> None:
        """Raise 403 unless allowed."""
        if not self.can(permission):
            raise PermissionDeniedError(NOT_ALLOWED)

    def as_caller(self) -> Caller:
        """The same person as a generic caller."""
        return Caller(organization=self.organization, permissions=self.permissions, user=self.user)


def user_read(user: User) -> UserRead:
    """The API shape of a user (the signed-in person)."""
    return UserRead(
        id=user.id,
        email=user.email,
        name=user.name,
        email_verified=user.is_verified,
        has_password=user.password_hash is not None,
        google_linked=user.google_sub is not None,
        created_at=user.created_at,
        deletion_scheduled_at=user.deletion_scheduled_at,
    )


def organization_read(org: Organization, membership: Membership) -> OrganizationRead:
    """The API shape of a workspace, with the caller's role."""
    return OrganizationRead(
        id=org.id,
        name=org.name,
        role=membership.role,
        deletion_scheduled_at=org.deletion_scheduled_at,
    )


class OrganizationService:
    """Organization operations for the signed-in user."""

    def __init__(self, db: AsyncSession, audit: AuditService) -> None:
        self._db = db
        self._repo = OrganizationRepository(db)
        self._audit = audit

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
            org = await self._repo.create(name=workspace_name(user.name), owner_id=user.id)
            await self._audit.record(
                AuditAction.ORG_CREATED,
                organization_id=org.id,
                actor_user_id=user.id,
                details={"name": org.name},
            )
            orgs = await self._repo.list_for_user(user.id)
        org, membership = orgs[0]
        user_session.active_organization_id = org.id
        await self._db.commit()
        return OrgContext(user, user_session, org, membership)

    async def list_for_user(self, user: User) -> list[OrganizationRead]:
        """The user's workspaces with roles."""
        return [organization_read(org, m) for org, m in await self._repo.list_for_user(user.id)]

    async def create(self, user: User, user_session: UserSession, name: str) -> OrganizationRead:
        """New workspace owned by the user; it becomes the active one."""
        org = await self._repo.create(name=name.strip(), owner_id=user.id)
        user_session.active_organization_id = org.id
        await self._audit.record(
            AuditAction.ORG_CREATED,
            organization_id=org.id,
            actor_user_id=user.id,
            details={"name": org.name},
        )
        await self._db.commit()
        found = await self._repo.get_for_user(org.id, user.id)
        assert found is not None
        return organization_read(found[0], found[1])

    async def rename(self, ctx: OrgContext, name: str) -> OrganizationRead:
        """Change the workspace name (owners and admins)."""
        ctx.require(Permission.ORG_UPDATE)
        org = await self._repo.lock(ctx.organization.id)
        assert org is not None
        old, new = org.name, name.strip()
        if old != new:
            org.name = new
            await self._audit.record(
                AuditAction.ORG_RENAMED,
                organization_id=org.id,
                actor_user_id=ctx.user.id,
                details={"from": old, "to": new},
            )
        await self._db.commit()
        return organization_read(org, ctx.membership)

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
            user=user_read(user),
            organizations=await self.list_for_user(user),
            active_organization_id=context.organization.id,
            permissions=sorted(context.permissions),
        )
