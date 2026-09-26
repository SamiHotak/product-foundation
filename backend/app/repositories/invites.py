"""Invite queries. Every workspace-side query takes the organization id."""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invite import Invite
from app.models.organization import Organization
from app.models.user import User


class InviteRepository:
    """Invites of a workspace, and lookup by token for the person invited."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, invite: Invite) -> Invite:
        """Insert an invite."""
        self._session.add(invite)
        await self._session.flush()
        return invite

    async def list_open(
        self, organization_id: uuid.UUID, now: datetime
    ) -> list[tuple[Invite, User | None]]:
        """Open (not accepted, not revoked, not expired) invites with who sent them."""
        rows = await self._session.execute(
            select(Invite, User)
            .outerjoin(User, User.id == Invite.invited_by_id)
            .where(
                Invite.organization_id == organization_id,
                Invite.accepted_at.is_(None),
                Invite.revoked_at.is_(None),
                Invite.expires_at > now,
            )
            .order_by(Invite.created_at.desc(), Invite.id)
        )
        return [(i, u) for i, u in rows.tuples()]

    async def get(self, invite_id: uuid.UUID, *, organization_id: uuid.UUID) -> Invite | None:
        """One invite of this workspace, locked until commit."""
        found: Invite | None = await self._session.scalar(
            select(Invite)
            .where(Invite.id == invite_id, Invite.organization_id == organization_id)
            .with_for_update()
        )
        return found

    async def get_unfinished_for_email(
        self, organization_id: uuid.UUID, email: str
    ) -> Invite | None:
        """The not-accepted, not-revoked invite for this email (maybe expired)."""
        found: Invite | None = await self._session.scalar(
            select(Invite)
            .where(
                Invite.organization_id == organization_id,
                Invite.email == email,
                Invite.accepted_at.is_(None),
                Invite.revoked_at.is_(None),
            )
            .with_for_update()
        )
        return found

    async def get_by_token_hash(
        self, token_hash: str, *, for_update: bool = False
    ) -> tuple[Invite, Organization, User | None] | None:
        """An invite by its link token, with the workspace and the person who sent it."""
        query = (
            select(Invite, Organization, User)
            .join(Organization, Organization.id == Invite.organization_id)
            .outerjoin(User, User.id == Invite.invited_by_id)
            .where(Invite.token_hash == token_hash)
        )
        if for_update:
            query = query.with_for_update(of=Invite)
        found = (await self._session.execute(query)).tuples().first()
        return (found[0], found[1], found[2]) if found else None
