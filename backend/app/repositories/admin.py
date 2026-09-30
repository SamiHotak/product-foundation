"""Queries across ALL workspaces, for app admins only (/admin).

This is the one place that reads data without an organization filter. Every route that
uses it requires a superuser (app/routers/admin.py).
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.billing import PAID_STATUSES, Subscription, UsageRecord
from app.models.file import FileStatus, StoredFile
from app.models.job import Job, JobStatus
from app.models.llm_call import LlmCall
from app.models.organization import Membership, Organization, Role
from app.models.user import User


def _like(term: str) -> str:
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


@dataclass(frozen=True)
class OrgUsageRow:
    """A workspace with its owner, plan and this month's usage."""

    organization: Organization
    subscription: Subscription | None
    members: int
    owner_email: str | None
    storage_bytes: int
    ai_requests_month: int
    ai_cost_micro_usd_month: int
    jobs_month: int


class AdminRepository:
    """Read-mostly queries over the whole app."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _count(self, query: Select[tuple[int]]) -> int:
        return int(await self._session.scalar(query) or 0)

    # --- overview ---------------------------------------------------------------------------

    async def totals(self, month: datetime, since: datetime) -> dict[str, int]:
        """Headline numbers."""
        return {
            "users": await self._count(select(func.count()).select_from(User)),
            "workspaces": await self._count(select(func.count()).select_from(Organization)),
            "paid_workspaces": await self._count(
                select(func.count())
                .select_from(Subscription)
                .where(Subscription.status.in_(PAID_STATUSES), Subscription.plan_id.is_not(None))
            ),
            "failed_jobs_7d": await self._count(
                select(func.count())
                .select_from(Job)
                .where(Job.status == JobStatus.FAILED, Job.finished_at >= since)
            ),
            "ai_requests_month": await self._count(
                select(func.count()).select_from(LlmCall).where(LlmCall.created_at >= month)
            ),
            "ai_cost_micro_usd_month": await self._count(
                select(func.coalesce(func.sum(LlmCall.cost_micro_usd), 0)).where(
                    LlmCall.created_at >= month
                )
            ),
            "storage_bytes": await self._count(
                select(func.coalesce(func.sum(StoredFile.size_bytes), 0)).where(
                    StoredFile.status != FileStatus.REJECTED
                )
            ),
        }

    # --- workspaces -------------------------------------------------------------------------

    async def organizations(
        self, *, search: str | None, limit: int, month: date
    ) -> list[OrgUsageRow]:
        """Workspaces with owner, plan, members and this month's usage, newest first."""
        members = (
            select(Membership.organization_id, func.count().label("n"))
            .group_by(Membership.organization_id)
            .subquery()
        )
        owners = (
            select(Membership.organization_id, User.email.label("owner_email"))
            .join(User, User.id == Membership.user_id)
            .where(Membership.role == Role.OWNER)
            .subquery()
        )
        storage = (
            select(StoredFile.organization_id, func.sum(StoredFile.size_bytes).label("bytes"))
            .where(StoredFile.status != FileStatus.REJECTED)
            .group_by(StoredFile.organization_id)
            .subquery()
        )
        ai = (
            select(
                LlmCall.organization_id,
                func.count().label("calls"),
                func.sum(LlmCall.cost_micro_usd).label("cost"),
            )
            .where(LlmCall.created_at >= month)
            .group_by(LlmCall.organization_id)
            .subquery()
        )
        jobs = (
            select(UsageRecord.organization_id, UsageRecord.count.label("jobs"))
            .where(UsageRecord.metric == "jobs_per_month", UsageRecord.period_start == month)
            .subquery()
        )
        query = (
            select(
                Organization,
                Subscription,
                func.coalesce(members.c.n, 0),
                owners.c.owner_email,
                func.coalesce(storage.c.bytes, 0),
                func.coalesce(ai.c.calls, 0),
                func.coalesce(ai.c.cost, 0),
                func.coalesce(jobs.c.jobs, 0),
            )
            .outerjoin(Subscription, Subscription.organization_id == Organization.id)
            .outerjoin(members, members.c.organization_id == Organization.id)
            .outerjoin(owners, owners.c.organization_id == Organization.id)
            .outerjoin(storage, storage.c.organization_id == Organization.id)
            .outerjoin(ai, ai.c.organization_id == Organization.id)
            .outerjoin(jobs, jobs.c.organization_id == Organization.id)
            .order_by(Organization.created_at.desc())
            .limit(limit)
        )
        if search:
            query = query.where(
                or_(
                    Organization.name.ilike(_like(search)),
                    owners.c.owner_email.ilike(_like(search)),
                )
            )
        rows = await self._session.execute(query)
        return [
            OrgUsageRow(
                organization=org,
                subscription=sub,
                members=int(n),
                owner_email=owner,
                storage_bytes=int(stored),
                ai_requests_month=int(calls),
                ai_cost_micro_usd_month=int(cost),
                jobs_month=int(job_count),
            )
            for org, sub, n, owner, stored, calls, cost, job_count in rows.tuples()
        ]

    # --- users ------------------------------------------------------------------------------

    async def users(self, *, search: str | None, limit: int) -> list[tuple[User, int]]:
        """People with how many workspaces they are in, newest first."""
        counts = (
            select(Membership.user_id, func.count().label("n"))
            .group_by(Membership.user_id)
            .subquery()
        )
        query = (
            select(User, func.coalesce(counts.c.n, 0))
            .outerjoin(counts, counts.c.user_id == User.id)
            .order_by(User.created_at.desc())
            .limit(limit)
        )
        if search:
            query = query.where(
                or_(User.email.ilike(_like(search)), User.name.ilike(_like(search)))
            )
        rows = await self._session.execute(query)
        return [(user, int(n)) for user, n in rows.tuples()]

    async def get_user(self, user_id: uuid.UUID) -> User | None:
        """One user."""
        return await self._session.get(User, user_id)

    async def organizations_of(self, user_id: uuid.UUID) -> list[uuid.UUID]:
        """Workspace ids the user belongs to."""
        rows = await self._session.scalars(
            select(Membership.organization_id).where(Membership.user_id == user_id)
        )
        return list(rows)

    # --- subscriptions ----------------------------------------------------------------------

    async def subscriptions(self, *, limit: int) -> list[tuple[Subscription, Organization]]:
        """Every billing row (paid ones first), with its workspace."""
        rows = await self._session.execute(
            select(Subscription, Organization)
            .join(Organization, Organization.id == Subscription.organization_id)
            .order_by(
                Subscription.status.in_(PAID_STATUSES).desc(),
                Subscription.updated_at.desc(),
            )
            .limit(limit)
        )
        return [(s, o) for s, o in rows.tuples()]

    # --- AI usage ---------------------------------------------------------------------------

    async def ai_usage(
        self, start: datetime, end: datetime
    ) -> list[tuple[uuid.UUID, str, str, str, int, int, int, int, int]]:
        """Per workspace and model: calls, failed calls, tokens, cost (for one month)."""
        rows = await self._session.execute(
            select(
                LlmCall.organization_id,
                Organization.name,
                LlmCall.task,
                LlmCall.model,
                func.count(),
                func.count().filter(LlmCall.status != "ok"),
                func.sum(LlmCall.input_tokens),
                func.sum(LlmCall.output_tokens),
                func.sum(LlmCall.cost_micro_usd),
            )
            .join(Organization, Organization.id == LlmCall.organization_id)
            .where(LlmCall.created_at >= start, LlmCall.created_at < end)
            .group_by(LlmCall.organization_id, Organization.name, LlmCall.task, LlmCall.model)
            .order_by(func.sum(LlmCall.cost_micro_usd).desc())
        )
        return [
            (org_id, name, task, model, int(calls), int(failed), int(inp), int(out), int(cost))
            for org_id, name, task, model, calls, failed, inp, out, cost in rows.tuples()
        ]

    # --- jobs -------------------------------------------------------------------------------

    async def failed_jobs(self, *, limit: int) -> list[tuple[Job, Organization, User | None]]:
        """The dead-letter list: jobs that failed for good, newest first."""
        rows = await self._session.execute(
            select(Job, Organization, User)
            .join(Organization, Organization.id == Job.organization_id)
            .outerjoin(User, User.id == Job.created_by_id)
            .where(Job.status == JobStatus.FAILED)
            .order_by(Job.finished_at.desc().nulls_last(), Job.id)
            .limit(limit)
        )
        return [(j, o, u) for j, o, u in rows.tuples()]

    async def get_job(self, job_id: uuid.UUID) -> Job | None:
        """One job (any workspace), locked until commit."""
        found: Job | None = await self._session.scalar(
            select(Job).where(Job.id == job_id).with_for_update()
        )
        return found
