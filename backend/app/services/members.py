"""Team management: list members, change roles, remove, leave, transfer ownership.

Rules (see app/core/permissions.py for who may do what):
- There is always exactly one owner. Only the owner can hand ownership to someone else.
- Nobody changes their own role or removes themselves (use "leave").
- Admins manage admins and members, never the owner.
- The owner can't leave: transfer ownership first, or delete the workspace.
Every change locks the workspace row first, so parallel clicks can't break these rules.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError
from app.core.permissions import Permission
from app.models.organization import Membership, Role
from app.models.user import User
from app.repositories.organizations import OrganizationRepository
from app.schemas.team import MemberRead
from app.services.audit import AuditAction, AuditService
from app.services.organizations import OrgContext


def member_read(membership: Membership, user: User, you: uuid.UUID) -> MemberRead:
    """The API shape of a member."""
    return MemberRead(
        user_id=user.id,
        name=user.name,
        email=user.email,
        role=membership.role,
        joined_at=membership.created_at,
        is_you=user.id == you,
    )


class MemberService:
    """Member operations in the caller's active workspace."""

    def __init__(self, db: AsyncSession, audit: AuditService) -> None:
        self._db = db
        self._orgs = OrganizationRepository(db)
        self._audit = audit

    async def list_members(self, ctx: OrgContext) -> list[MemberRead]:
        """Everyone in the workspace (every member may see the team)."""
        ctx.require(Permission.MEMBERS_READ)
        rows = await self._orgs.list_members(ctx.organization.id)
        return [member_read(m, u, ctx.user.id) for m, u in rows]

    async def _target(self, ctx: OrgContext, user_id: uuid.UUID) -> tuple[Membership, User]:
        """Lock the workspace, then load the member (404 if not in this workspace)."""
        await self._orgs.lock(ctx.organization.id)
        found = await self._orgs.get_membership(ctx.organization.id, user_id)
        if found is None:
            raise NotFoundError("This person is not in this workspace.")
        return found

    async def change_role(self, ctx: OrgContext, user_id: uuid.UUID, role: Role) -> MemberRead:
        """Make someone an admin or a member."""
        ctx.require(Permission.MEMBERS_MANAGE)
        if role is Role.OWNER:
            raise ConflictError("Use “Transfer ownership” to make someone the owner.")
        if user_id == ctx.user.id:
            raise ConflictError("You can't change your own role.")
        membership, user = await self._target(ctx, user_id)
        if membership.role is Role.OWNER:
            raise PermissionDeniedError(
                "The owner's role can't be changed. The owner can transfer ownership."
            )
        old = membership.role
        if old is not role:
            membership.role = role
            await self._audit.record(
                AuditAction.MEMBER_ROLE_CHANGED,
                organization_id=ctx.organization.id,
                actor_user_id=ctx.user.id,
                target_type="user",
                target_id=user.id,
                details={"email": user.email, "from": old.value, "to": role.value},
            )
        await self._db.commit()
        return member_read(membership, user, ctx.user.id)

    async def remove(self, ctx: OrgContext, user_id: uuid.UUID) -> None:
        """Remove someone from the workspace. Their account stays; they lose access here."""
        ctx.require(Permission.MEMBERS_MANAGE)
        if user_id == ctx.user.id:
            raise ConflictError("To remove yourself, use “Leave workspace”.")
        membership, user = await self._target(ctx, user_id)
        if membership.role is Role.OWNER:
            raise PermissionDeniedError("The owner can't be removed.")
        await self._orgs.remove_member(ctx.organization.id, user_id)
        await self._audit.record(
            AuditAction.MEMBER_REMOVED,
            organization_id=ctx.organization.id,
            actor_user_id=ctx.user.id,
            target_type="user",
            target_id=user.id,
            details={"email": user.email, "name": user.name, "role": membership.role.value},
        )
        await self._db.commit()

    async def leave(self, ctx: OrgContext) -> None:
        """Leave the active workspace. The next request opens another one."""
        await self._orgs.lock(ctx.organization.id)
        if ctx.membership.role is Role.OWNER:
            raise ConflictError(
                "The owner can't leave. Transfer ownership to someone first, "
                "or delete the workspace."
            )
        await self._orgs.remove_member(ctx.organization.id, ctx.user.id)
        await self._audit.record(
            AuditAction.MEMBER_LEFT,
            organization_id=ctx.organization.id,
            actor_user_id=ctx.user.id,
            target_type="user",
            target_id=ctx.user.id,
            details={"email": ctx.user.email, "role": ctx.membership.role.value},
        )
        ctx.session.active_organization_id = None
        await self._db.commit()

    async def transfer_ownership(self, ctx: OrgContext, user_id: uuid.UUID) -> list[MemberRead]:
        """Make another member the owner. The old owner becomes an admin."""
        ctx.require(Permission.OWNERSHIP_TRANSFER)
        if user_id == ctx.user.id:
            raise ConflictError("You are already the owner.")
        target, user = await self._target(ctx, user_id)
        mine = await self._orgs.get_membership(ctx.organization.id, ctx.user.id)
        if mine is None or mine[0].role is not Role.OWNER:  # changed since the request started
            raise PermissionDeniedError("Only the owner can transfer ownership.")
        mine[0].role = Role.ADMIN
        await self._db.flush()
        target.role = Role.OWNER
        await self._audit.record(
            AuditAction.ORG_OWNERSHIP_TRANSFERRED,
            organization_id=ctx.organization.id,
            actor_user_id=ctx.user.id,
            target_type="user",
            target_id=user.id,
            details={"from": ctx.user.email, "to": user.email},
        )
        await self._db.commit()
        rows = await self._orgs.list_members(ctx.organization.id)
        return [member_read(m, u, ctx.user.id) for m, u in rows]
