"""Queries for the nightly GDPR purge (sync, runs in the Celery worker)."""

import uuid
from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, aliased

from app.models.organization import Membership, Organization, Role
from app.models.user import User


class SyncDeletionRepository:
    """Find what is due for deletion, and delete it (foreign keys cascade the rest)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def users_due(self, now: datetime) -> list[uuid.UUID]:
        """Users whose deletion date has passed."""
        return list(
            self._session.scalars(
                select(User.id).where(
                    User.deletion_scheduled_at.is_not(None), User.deletion_scheduled_at <= now
                )
            )
        )

    def orgs_due(self, now: datetime) -> list[uuid.UUID]:
        """Workspaces whose deletion date has passed."""
        return list(
            self._session.scalars(
                select(Organization.id).where(
                    Organization.deletion_scheduled_at.is_not(None),
                    Organization.deletion_scheduled_at <= now,
                )
            )
        )

    def lock_user(self, user_id: uuid.UUID) -> User | None:
        """The user, locked until commit."""
        return self._session.get(User, user_id, with_for_update=True, populate_existing=True)

    def lock_org(self, organization_id: uuid.UUID) -> Organization | None:
        """The workspace, locked until commit."""
        return self._session.get(
            Organization, organization_id, with_for_update=True, populate_existing=True
        )

    def memberships(self, user_id: uuid.UUID) -> list[tuple[Membership, int]]:
        """The user's memberships, each with the number of people in that workspace."""
        other = aliased(Membership)
        size = (
            select(func.count())
            .select_from(other)
            .where(other.organization_id == Membership.organization_id)
            .correlate(Membership)
            .scalar_subquery()
        )
        rows = self._session.execute(select(Membership, size).where(Membership.user_id == user_id))
        return [(m, int(n)) for m, n in rows.tuples()]

    def successor(
        self, organization_id: uuid.UUID, leaving_user_id: uuid.UUID
    ) -> Membership | None:
        """Who becomes owner when the owner's account is deleted: the longest-standing
        admin, else the longest-standing member."""
        rows = self._session.scalars(
            select(Membership)
            .where(
                Membership.organization_id == organization_id,
                Membership.user_id != leaving_user_id,
            )
            .order_by(Membership.created_at, Membership.id)
        )
        candidates = list(rows)
        admins = [m for m in candidates if m.role is Role.ADMIN]
        pool = admins or candidates
        return pool[0] if pool else None

    def delete_user(self, user_id: uuid.UUID) -> None:
        """Delete the user. Sessions, memberships, tokens and account exports cascade."""
        self._session.execute(delete(User).where(User.id == user_id))

    def delete_org(self, organization_id: uuid.UUID) -> None:
        """Delete the workspace. All its data (jobs, invites, keys, audit log) cascades."""
        self._session.execute(delete(Organization).where(Organization.id == organization_id))
