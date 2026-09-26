"""GDPR data exports, API side: start an export job, list exports, download a ZIP.

The ZIP itself is built in the worker (app/services/export_builder.py).
- Account export: anyone, for their own data.
- Workspace export: owners and admins (Permission.ORG_EXPORT).
Each person can start a few exports per hour (building a ZIP costs work).
"""

import uuid
from datetime import timedelta

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError, NotFoundError, RateLimitedError
from app.core.permissions import Permission
from app.core.rate_limit import RateLimiter
from app.models.data_export import DataExport, ExportScope
from app.repositories.exports import ExportRepository
from app.schemas.privacy import ExportRead
from app.services.audit import AuditAction, AuditService
from app.services.jobs import JobService
from app.services.organizations import OrgContext
from app.services.sessions import utcnow

EXPORTS_PER_USER_PER_HOUR = 5


class ExportNotReadyError(AppError):
    """The ZIP is still being built."""

    status_code = status.HTTP_409_CONFLICT
    code = "export_not_ready"


def _slug(text: str) -> str:
    cleaned = "".join(c.lower() if c.isalnum() else "-" for c in text).strip("-")
    return "-".join(part for part in cleaned.split("-") if part)[:40] or "workspace"


def export_read(export: DataExport, api_prefix: str) -> ExportRead:
    """The API shape of an export."""
    return ExportRead(
        id=export.id,
        scope=export.scope,
        job_id=export.job_id,
        filename=export.filename,
        ready=export.size_bytes is not None,
        size_bytes=export.size_bytes,
        created_at=export.created_at,
        expires_at=export.expires_at,
        download_url=f"{api_prefix}/exports/{export.id}/download",
    )


class ExportService:
    """Start, list and download exports. One instance per request."""

    def __init__(
        self,
        db: AsyncSession,
        settings: Settings,
        limiter: RateLimiter,
        audit: AuditService,
        jobs: JobService,
    ) -> None:
        self._db = db
        self._settings = settings
        self._limiter = limiter
        self._audit = audit
        self._jobs = jobs
        self._repo = ExportRepository(db)

    async def _count(self, ctx: OrgContext) -> None:
        wait = await self._limiter.hit(
            f"exports:{ctx.user.id}", limit=EXPORTS_PER_USER_PER_HOUR, window_seconds=3600
        )
        if wait is not None:
            raise RateLimitedError(
                "You started several exports in the last hour. Try again later.",
                retry_after=wait,
            )

    async def _start(self, ctx: OrgContext, export: DataExport, action: AuditAction) -> ExportRead:
        await self._repo.add(export)
        await self._audit.record(
            action,
            organization_id=ctx.organization.id
            if export.scope is ExportScope.ORGANIZATION
            else None,
            actor_user_id=ctx.user.id,
            target_type="export",
            target_id=export.id,
        )
        # enqueue() commits (export row + audit + job row) BEFORE the worker gets the task.
        job = await self._jobs.enqueue(
            "data_export",
            {"export_id": str(export.id)},
            organization_id=ctx.organization.id,
            created_by_id=ctx.user.id,
        )
        export.job_id = job.id
        await self._db.commit()
        return export_read(export, self._settings.api_prefix)

    async def start_account_export(self, ctx: OrgContext) -> ExportRead:
        """Export everything we store about the signed-in person."""
        await self._count(ctx)
        now = utcnow()
        export = DataExport(
            scope=ExportScope.ACCOUNT,
            user_id=ctx.user.id,
            requested_by_id=ctx.user.id,
            filename=f"my-data-{now:%Y-%m-%d}.zip",
            expires_at=now + timedelta(days=self._settings.export_retention_days),
        )
        return await self._start(ctx, export, AuditAction.ACCOUNT_EXPORTED)

    async def start_org_export(self, ctx: OrgContext) -> ExportRead:
        """Export all data of the active workspace."""
        ctx.require(Permission.ORG_EXPORT)
        await self._count(ctx)
        now = utcnow()
        export = DataExport(
            scope=ExportScope.ORGANIZATION,
            organization_id=ctx.organization.id,
            requested_by_id=ctx.user.id,
            filename=f"{_slug(ctx.organization.name)}-export-{now:%Y-%m-%d}.zip",
            expires_at=now + timedelta(days=self._settings.export_retention_days),
        )
        return await self._start(ctx, export, AuditAction.ORG_EXPORTED)

    async def list_exports(self, ctx: OrgContext) -> list[ExportRead]:
        """Your own recent exports, plus the workspace's if you may export it."""
        now = utcnow()
        items = await self._repo.list_for_user(ctx.user.id, now)
        if ctx.can(Permission.ORG_EXPORT):
            items += await self._repo.list_for_org(ctx.organization.id, now)
        items.sort(key=lambda e: e.created_at, reverse=True)
        return [export_read(e, self._settings.api_prefix) for e in items]

    async def download(self, ctx: OrgContext, export_id: uuid.UUID) -> DataExport:
        """The finished export, if the caller may have it (others get 404)."""
        export = await self._repo.get_with_content(export_id)
        allowed = export is not None and (
            (export.scope is ExportScope.ACCOUNT and export.user_id == ctx.user.id)
            or (
                export.scope is ExportScope.ORGANIZATION
                and export.organization_id == ctx.organization.id
                and ctx.can(Permission.ORG_EXPORT)
            )
        )
        if export is None or not allowed or export.expires_at <= utcnow():
            raise NotFoundError("This export does not exist or has expired.")
        if export.content is None:
            raise ExportNotReadyError("The export is still being prepared. Try again in a moment.")
        return export
