"""Data export queries.

- `ExportRepository` (async): the API creates exports and serves downloads.
- `SyncExportReader` (sync): the worker reads everything that goes into a ZIP.
  Every read is scoped to ONE user or ONE workspace.
"""

import uuid
from datetime import datetime

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, undefer

from app.models.api_key import ApiKey
from app.models.audit_log import AuditLog
from app.models.data_export import DataExport, ExportScope
from app.models.invite import Invite
from app.models.job import Job
from app.models.organization import Membership, Organization
from app.models.session import UserSession
from app.models.user import User


class ExportRepository:
    """Exports for the API. Downloads check who may see them."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, export: DataExport) -> DataExport:
        """Insert an export row (the job fills in the content)."""
        self._session.add(export)
        await self._session.flush()
        return export

    async def list_for_user(self, user_id: uuid.UUID, now: datetime) -> list[DataExport]:
        """This person's own account exports that are not expired, newest first."""
        rows = await self._session.scalars(
            select(DataExport)
            .where(
                DataExport.scope == ExportScope.ACCOUNT,
                DataExport.user_id == user_id,
                DataExport.expires_at > now,
            )
            .order_by(DataExport.created_at.desc())
            .limit(5)
        )
        return list(rows)

    async def list_for_org(self, organization_id: uuid.UUID, now: datetime) -> list[DataExport]:
        """Workspace exports that are not expired, newest first."""
        rows = await self._session.scalars(
            select(DataExport)
            .where(
                DataExport.scope == ExportScope.ORGANIZATION,
                DataExport.organization_id == organization_id,
                DataExport.expires_at > now,
            )
            .order_by(DataExport.created_at.desc())
            .limit(5)
        )
        return list(rows)

    async def get_with_content(self, export_id: uuid.UUID) -> DataExport | None:
        """One export including the file. The service checks access."""
        found: DataExport | None = await self._session.scalar(
            select(DataExport)
            .where(DataExport.id == export_id)
            .options(undefer(DataExport.content))
        )
        return found

    async def set_job(self, export: DataExport, job_id: uuid.UUID) -> None:
        """Link the export to the job that builds it."""
        await self._session.execute(
            update(DataExport).where(DataExport.id == export.id).values(job_id=job_id)
        )


class SyncExportReader:
    """Worker-side reads and writes for building an export ZIP."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_export(self, export_id: uuid.UUID) -> DataExport | None:
        """The export row."""
        return self._session.get(DataExport, export_id)

    def save_content(self, export: DataExport, content: bytes) -> None:
        """Store the finished ZIP."""
        export.content = content
        export.size_bytes = len(content)

    # --- account -------------------------------------------------------------------------

    def user(self, user_id: uuid.UUID) -> User | None:
        """The user."""
        return self._session.get(User, user_id)

    def memberships(self, user_id: uuid.UUID) -> list[tuple[Membership, Organization]]:
        """The user's workspaces."""
        rows = self._session.execute(
            select(Membership, Organization)
            .join(Organization, Organization.id == Membership.organization_id)
            .where(Membership.user_id == user_id)
            .order_by(Membership.created_at)
        )
        return [(m, o) for m, o in rows.tuples()]

    def sessions(self, user_id: uuid.UUID) -> list[UserSession]:
        """The user's signed-in browsers."""
        return list(
            self._session.scalars(
                select(UserSession)
                .where(UserSession.user_id == user_id)
                .order_by(UserSession.created_at)
            )
        )

    def activity(self, user_id: uuid.UUID) -> list[AuditLog]:
        """Everything the user did (account and workspace events)."""
        return list(
            self._session.scalars(
                select(AuditLog)
                .where(AuditLog.actor_user_id == user_id)
                .order_by(AuditLog.created_at)
            )
        )

    def jobs_by_user(self, user_id: uuid.UUID) -> list[Job]:
        """Jobs the user started."""
        return list(
            self._session.scalars(
                select(Job).where(Job.created_by_id == user_id).order_by(Job.created_at)
            )
        )

    # --- workspace -----------------------------------------------------------------------

    def organization(self, organization_id: uuid.UUID) -> Organization | None:
        """The workspace."""
        return self._session.get(Organization, organization_id)

    def members(self, organization_id: uuid.UUID) -> list[tuple[Membership, User]]:
        """The workspace's members."""
        rows = self._session.execute(
            select(Membership, User)
            .join(User, User.id == Membership.user_id)
            .where(Membership.organization_id == organization_id)
            .order_by(Membership.created_at)
        )
        return [(m, u) for m, u in rows.tuples()]

    def invites(self, organization_id: uuid.UUID) -> list[Invite]:
        """All invites of the workspace."""
        return list(
            self._session.scalars(
                select(Invite)
                .where(Invite.organization_id == organization_id)
                .order_by(Invite.created_at)
            )
        )

    def api_keys(self, organization_id: uuid.UUID) -> list[ApiKey]:
        """All API keys of the workspace (hashes are never exported)."""
        return list(
            self._session.scalars(
                select(ApiKey)
                .where(ApiKey.organization_id == organization_id)
                .order_by(ApiKey.created_at)
            )
        )

    def audit_log(self, organization_id: uuid.UUID) -> list[AuditLog]:
        """The workspace's audit log."""
        return list(
            self._session.scalars(
                select(AuditLog)
                .where(AuditLog.organization_id == organization_id)
                .order_by(AuditLog.created_at)
            )
        )

    def jobs(self, organization_id: uuid.UUID) -> list[Job]:
        """The workspace's jobs."""
        return list(
            self._session.scalars(
                select(Job).where(Job.organization_id == organization_id).order_by(Job.created_at)
            )
        )


class SyncMaintenance:
    """Nightly clean-up queries (expired exports, old audit rows)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def delete_expired_exports(self, now: datetime) -> int:
        """Remove export ZIPs after their download window."""
        result = self._session.execute(delete(DataExport).where(DataExport.expires_at <= now))
        return int(getattr(result, "rowcount", 0))

    def delete_old_audit(self, before: datetime) -> int:
        """Remove audit events older than the retention period."""
        result = self._session.execute(delete(AuditLog).where(AuditLog.created_at < before))
        return int(getattr(result, "rowcount", 0))

    def delete_account_events(self, user_id: uuid.UUID) -> int:
        """Remove a deleted user's personal events (sign-ins etc., not workspace events)."""
        result = self._session.execute(
            delete(AuditLog).where(
                AuditLog.actor_user_id == user_id, AuditLog.organization_id.is_(None)
            )
        )
        return int(getattr(result, "rowcount", 0))
