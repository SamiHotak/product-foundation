"""The app admin area (/admin): numbers across all workspaces, failed jobs, the AI kill
switch, and viewing the app as a user (impersonation) for support.

Only users with `is_superuser` get here (give it with `make admin email=...`). Every
change is written to the audit log. Viewing as a user is also recorded in THAT user's
workspaces, so customers can see when support looked at their account.
"""

import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError
from app.core.logging import get_logger
from app.llm.gateway import LlmGateway
from app.models.job import JobStatus
from app.models.session import UserSession
from app.models.system_flag import Flag
from app.models.user import User
from app.repositories.admin import AdminRepository
from app.repositories.sessions import SessionRepository
from app.schemas.admin import (
    AdminAiUsageRow,
    AdminFailedJob,
    AdminOrganization,
    AdminOverview,
    AdminSubscription,
    AdminUsage,
    AdminUser,
)
from app.services.audit import AuditAction, AuditService
from app.services.flags import read_flag_async, write_flag
from app.services.jobs import Dispatcher
from app.services.sessions import SessionService
from app.services.usage import month_start, next_month_start

logger = get_logger(__name__)

ADMINS_ONLY = "Only admins of the app can open this."


def _usd(micro: int) -> float:
    return round(micro / 1_000_000, 6)


def _month_bounds(month: date) -> tuple[datetime, datetime]:
    start = datetime(month.year, month.month, 1, tzinfo=UTC)
    return start, datetime.combine(next_month_start(start), datetime.min.time(), tzinfo=UTC)


class AdminService:
    """Admin operations for one request. The caller is checked by the router."""

    def __init__(
        self,
        db: AsyncSession,
        settings: Settings,
        audit: AuditService,
        sessions: SessionService,
        gateway: LlmGateway,
        dispatch: Dispatcher,
    ) -> None:
        self._db = db
        self._settings = settings
        self._audit = audit
        self._sessions = sessions
        self._gateway = gateway
        self._dispatch = dispatch
        self._repo = AdminRepository(db)

    @staticmethod
    def require_admin(user: User, user_session: UserSession) -> None:
        """403 unless an app admin, signed in as themselves (not viewing as someone)."""
        if not user.is_superuser or user_session.impersonator_id is not None:
            raise PermissionDeniedError(ADMINS_ONLY)

    # --- reading ----------------------------------------------------------------------------

    async def overview(self) -> AdminOverview:
        """Headline numbers."""
        now = datetime.now(UTC)
        month = month_start(now)
        start, _ = _month_bounds(month)
        totals = await self._repo.totals(start, now - timedelta(days=7))
        return AdminOverview(
            users=totals["users"],
            workspaces=totals["workspaces"],
            paid_workspaces=totals["paid_workspaces"],
            failed_jobs_7d=totals["failed_jobs_7d"],
            ai_requests_month=totals["ai_requests_month"],
            ai_cost_usd_month=_usd(totals["ai_cost_micro_usd_month"]),
            storage_bytes=totals["storage_bytes"],
            ai_paused=await read_flag_async(self._db, Flag.AI_PAUSED),
            ai_provider=self._gateway.provider_name,
            month=month,
        )

    async def organizations(self, search: str | None, limit: int) -> list[AdminOrganization]:
        """Workspaces with usage of this month."""
        month = month_start(datetime.now(UTC))
        rows = await self._repo.organizations(search=search, limit=limit, month=month)
        return [
            AdminOrganization(
                id=row.organization.id,
                name=row.organization.name,
                created_at=row.organization.created_at,
                owner_email=row.owner_email,
                members=row.members,
                plan_id=(
                    row.subscription.plan_id
                    if row.subscription is not None and row.subscription.is_paid
                    else None
                ),
                subscription_status=row.subscription.status if row.subscription else None,
                storage_bytes=row.storage_bytes,
                jobs_month=row.jobs_month,
                ai_requests_month=row.ai_requests_month,
                ai_cost_usd_month=_usd(row.ai_cost_micro_usd_month),
                deletion_scheduled_at=row.organization.deletion_scheduled_at,
            )
            for row in rows
        ]

    async def users(self, search: str | None, limit: int) -> list[AdminUser]:
        """Users, newest first."""
        return [
            AdminUser(
                id=u.id,
                name=u.name,
                email=u.email,
                email_verified=u.is_verified,
                is_superuser=u.is_superuser,
                is_demo=u.is_demo,
                is_active=u.is_active,
                workspaces=n,
                created_at=u.created_at,
                last_login_at=u.last_login_at,
                deletion_scheduled_at=u.deletion_scheduled_at,
            )
            for u, n in await self._repo.users(search=search, limit=limit)
        ]

    async def subscriptions(self, limit: int) -> list[AdminSubscription]:
        """The subscriptions table, paid first."""
        return [
            AdminSubscription(
                organization_id=org.id,
                organization_name=org.name,
                plan_id=sub.plan_id,
                status=sub.status,
                interval=sub.interval,
                current_period_end=sub.current_period_end,
                cancel_at_period_end=sub.cancel_at_period_end,
                trial_end=sub.trial_end,
                stripe_customer_id=sub.stripe_customer_id,
                stripe_subscription_id=sub.stripe_subscription_id,
                updated_at=sub.updated_at,
            )
            for sub, org in await self._repo.subscriptions(limit=limit)
        ]

    async def usage(self, month: date | None) -> AdminUsage:
        """AI requests and cost per workspace, task and model in one month."""
        month = (
            month_start(datetime.now(UTC)) if month is None else date(month.year, month.month, 1)
        )
        start, end = _month_bounds(month)
        rows = [
            AdminAiUsageRow(
                organization_id=org_id,
                organization_name=name,
                task=task,
                model=model,
                requests=calls,
                failed=failed,
                input_tokens=inp,
                output_tokens=out,
                cost_usd=_usd(cost),
            )
            for org_id, name, task, model, calls, failed, inp, out, cost in (
                await self._repo.ai_usage(start, end)
            )
        ]
        return AdminUsage(
            month=month,
            rows=rows,
            total_requests=sum(r.requests for r in rows),
            total_cost_usd=round(sum(r.cost_usd for r in rows), 6),
        )

    async def failed_jobs(self, limit: int) -> list[AdminFailedJob]:
        """The dead-letter list."""
        return [
            AdminFailedJob(
                id=job.id,
                kind=job.kind,
                organization_id=org.id,
                organization_name=org.name,
                started_by=user.email if user else None,
                error=job.error,
                attempts=job.attempts,
                created_at=job.created_at,
                finished_at=job.finished_at,
            )
            for job, org, user in await self._repo.failed_jobs(limit=limit)
        ]

    # --- changing ---------------------------------------------------------------------------

    async def retry_job(self, admin: User, job_id: uuid.UUID) -> None:
        """Run a failed job again (same job id, same parameters)."""
        job = await self._repo.get_job(job_id)
        if job is None:
            raise NotFoundError("This job does not exist.")
        if job.status is not JobStatus.FAILED:
            raise ConflictError("Only failed jobs can be retried.")
        job.status = JobStatus.QUEUED
        job.error = None
        job.progress = 0
        job.message = "Queued again by an admin"
        job.finished_at = None
        await self._audit.record(
            AuditAction.ADMIN_JOB_RETRIED,
            organization_id=job.organization_id,
            actor_user_id=admin.id,
            target_type="job",
            target_id=job.id,
            details={"kind": job.kind},
        )
        await self._db.commit()
        await self._dispatch(job)
        logger.info("admin_job_retried", job_id=str(job.id))

    async def set_ai_paused(self, admin: User, paused: bool) -> bool:
        """The AI kill switch. Takes effect for the next AI request, everywhere."""
        await write_flag(self._db, Flag.AI_PAUSED, paused, user_id=admin.id)
        await self._audit.record(
            AuditAction.ADMIN_AI_SWITCHED,
            organization_id=None,
            actor_user_id=admin.id,
            details={"paused": paused},
        )
        await self._db.commit()
        logger.warning("ai_kill_switch", paused=paused, admin_id=str(admin.id))
        return paused

    async def start_impersonation(
        self, admin: User, target_id: uuid.UUID, *, ip: str | None, user_agent: str | None
    ) -> str:
        """Start viewing the app as a user. Returns the new session's cookie token."""
        target = await self._repo.get_user(target_id)
        if target is None:
            raise NotFoundError("This user does not exist.")
        if target.id == admin.id:
            raise ConflictError("You can't view the app as yourself.")
        if target.is_superuser:
            raise PermissionDeniedError("Other admins can't be viewed as.")
        if not target.is_active:
            raise ConflictError("This account is deactivated.")
        minutes = self._settings.impersonation_minutes
        token, _ = await self._sessions.create(
            user_id=target.id,
            organization_id=None,
            ip=ip,
            user_agent=user_agent,
            lifetime=timedelta(minutes=minutes),
            impersonator_id=admin.id,
        )
        details = {"user": target.email, "minutes": minutes}
        await self._audit.record(
            AuditAction.ADMIN_IMPERSONATION_STARTED,
            organization_id=None,
            actor_user_id=admin.id,
            target_type="user",
            target_id=target.id,
            details=details,
        )
        for org_id in await self._repo.organizations_of(target.id):
            await self._audit.record(
                AuditAction.ADMIN_IMPERSONATION_STARTED,
                organization_id=org_id,
                actor_user_id=admin.id,
                target_type="user",
                target_id=target.id,
                details=details,
            )
        await self._db.commit()
        logger.warning("impersonation_started", admin_id=str(admin.id), user_id=str(target.id))
        return token

    async def stop_impersonation(self, user_session: UserSession, admin_token: str) -> bool:
        """End the view. True if the admin's own session is still valid (switch back to it)."""
        admin_id = user_session.impersonator_id
        if admin_id is None:
            raise ConflictError("You are not viewing the app as someone else.")
        await SessionRepository(self._db).delete(user_session.id)
        await self._audit.record(
            AuditAction.ADMIN_IMPERSONATION_ENDED,
            organization_id=None,
            actor_user_id=admin_id,
            target_type="user",
            target_id=user_session.user_id,
        )
        await self._db.commit()
        own = await self._sessions.resolve(admin_token)
        restored = own is not None and own.user_id == admin_id and own.impersonator_id is None
        if self._db.dirty:
            await self._db.commit()
        return restored
