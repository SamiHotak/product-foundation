"""Plan limits and usage metering.

The plan of a workspace = its paid subscription (while Stripe says trialing / active /
past_due), else the free plan. Limits come from app/core/plans.py through the catalog.

Three kinds of limits:
- metered per month   `consume()` adds to a counter in the same transaction as the work.
                      One SQL statement checks and adds, so parallel requests can't pass it.
                      (jobs_per_month, ai_requests_per_month)
- seats               `check_seats()` counts members + open invites (callers lock the org row).
- things you keep     `check_api_keys()` counts active keys, `check_storage()` the bytes of
                      stored files (callers lock the org row).

Background workers (e.g. the LLM gateway) use `SyncUsageMeter`: the same rules with a
normal (sync) database session.

When a limit is reached, `LimitReachedError` (HTTP 402, code "limit_reached") tells the
person what happened and that an upgrade helps. The UI shows an "See plans" link with it.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Literal

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.plans import PlanCatalog, PlanDefinition
from app.models.billing import Subscription
from app.repositories.billing import BillingRepository, SyncBillingRepository

# Metered per calendar month (a counter in usage_records).
MeteredMetric = Literal["jobs_per_month", "ai_requests_per_month"]
Metric = Literal["members", "jobs_per_month", "api_keys", "storage_mb", "ai_requests_per_month"]

LABELS: dict[str, str] = {
    "members": "People in this workspace",
    "jobs_per_month": "Background jobs this month",
    "api_keys": "API keys",
    "storage_mb": "File storage",
    "ai_requests_per_month": "AI requests this month",
}

MB = 1024 * 1024


class LimitReachedError(AppError):
    """The workspace's plan does not allow more of this."""

    status_code = status.HTTP_402_PAYMENT_REQUIRED
    code = "limit_reached"


@dataclass(frozen=True)
class UsageLine:
    """How much of one limit a workspace uses."""

    metric: str
    label: str
    used: int
    limit: int | None
    unit: Literal["count", "mb"] = "count"


def month_start(now: datetime) -> date:
    """First day of the calendar month (UTC) that `now` is in."""
    now = now.astimezone(UTC)
    return date(now.year, now.month, 1)


def next_month_start(now: datetime) -> date:
    """First day of the next calendar month (UTC): when monthly counters start from 0."""
    start = month_start(now)
    return date(start.year + start.month // 12, start.month % 12 + 1, 1)


def _limit(plan: PlanDefinition, metric: str) -> int | None:
    value: int | None = getattr(plan.limits, metric)
    return value


def effective_plan(sub: Subscription | None, catalog: PlanCatalog) -> PlanDefinition:
    """The plan whose limits apply: the paid one while Stripe says so, else free."""
    if sub is not None and sub.is_paid:
        plan = catalog.get(sub.plan_id)
        if plan is not None:
            return plan
    return catalog.free


def limit_error(plan: PlanDefinition, metric: str, used: int, limit: int) -> LimitReachedError:
    """The 402 error with a message people understand."""
    messages = {
        "members": (
            f"The {plan.name} plan allows {limit} "
            f"{'person' if limit == 1 else 'people'} in a workspace "
            "(open invites count too). Upgrade to add more people."
        ),
        "jobs_per_month": (
            f"This workspace used all {limit:,} background jobs of the {plan.name} plan "
            "this month. Upgrade to run more, or wait until the 1st of next month."
        ),
        "api_keys": (
            f"The {plan.name} plan allows {limit} API {'key' if limit == 1 else 'keys'}. "
            "Upgrade, or revoke a key you don't use any more."
        ),
        "storage_mb": (
            f"This file doesn't fit: the {plan.name} plan includes {_storage_text(limit)} of "
            "files. Delete files you don't need, or upgrade for more space."
        ),
        "ai_requests_per_month": (
            f"This workspace used all {limit:,} AI requests of the {plan.name} plan this month. "
            "Upgrade to use more, or wait until the 1st of next month."
        ),
    }
    return LimitReachedError(
        messages[metric],
        details={
            "metric": metric,
            "limit": limit,
            "used": used,
            "plan_id": plan.id,
            "plan_name": plan.name,
        },
    )


def _storage_text(mb: int) -> str:
    return f"{mb / 1024:g} GB" if mb >= 1024 else f"{mb} MB"


class UsageService:
    """Reads plans and limits, and meters usage. One instance per request."""

    def __init__(self, db: AsyncSession, catalog: PlanCatalog) -> None:
        self._repo = BillingRepository(db)
        self._catalog = catalog

    async def plan_for(self, organization_id: uuid.UUID) -> PlanDefinition:
        """The plan whose limits apply right now."""
        return effective_plan(await self._repo.get_subscription(organization_id), self._catalog)

    async def check_available(
        self, organization_id: uuid.UUID, metric: MeteredMetric, *, now: datetime | None = None
    ) -> None:
        """Raise LimitReachedError if this month's allowance is used up (counts nothing).

        For work that is metered LATER (e.g. an AI job counts when the worker calls the
        model): the person gets the 402 right away instead of a failed job.
        """
        now = now or datetime.now(UTC)
        plan = await self.plan_for(organization_id)
        limit = _limit(plan, metric)
        if limit is None:
            return
        used = await self._repo.get_usage(organization_id, metric, month_start(now))
        if used >= limit:
            raise limit_error(plan, metric, used, limit)

    async def consume(
        self,
        organization_id: uuid.UUID,
        metric: MeteredMetric,
        amount: int = 1,
        *,
        now: datetime | None = None,
    ) -> None:
        """Count `amount` for this month, or raise LimitReachedError (nothing is counted)."""
        now = now or datetime.now(UTC)
        plan = await self.plan_for(organization_id)
        limit = _limit(plan, metric)
        total = await self._repo.add_usage(
            organization_id, metric, month_start(now), amount, limit=limit
        )
        if total is None:
            assert limit is not None
            used = await self._repo.get_usage(organization_id, metric, month_start(now))
            raise limit_error(plan, metric, used, limit)

    async def release(
        self,
        organization_id: uuid.UUID,
        metric: MeteredMetric,
        amount: int = 1,
        *,
        now: datetime | None = None,
    ) -> None:
        """Give back usage that did not happen."""
        now = now or datetime.now(UTC)
        await self._repo.release_usage(organization_id, metric, month_start(now), amount)

    async def check_seats(
        self,
        organization_id: uuid.UUID,
        *,
        now: datetime,
        count_invites: bool,
        replacing_invite_for: str | None = None,
    ) -> None:
        """Raise unless one more person fits.

        Inviting counts open invites too (each will take a seat). Accepting an invite only
        counts members, because that invite was already counted when it was sent.
        """
        plan = await self.plan_for(organization_id)
        limit = plan.limits.members
        if limit is None:
            return
        used = await self._repo.count_members(organization_id)
        if count_invites:
            used += await self._repo.count_open_invites(
                organization_id, now, except_email=replacing_invite_for
            )
        if used + 1 > limit:
            raise limit_error(plan, "members", used, limit)

    async def check_api_keys(self, organization_id: uuid.UUID, *, now: datetime) -> None:
        """Raise unless one more API key fits."""
        plan = await self.plan_for(organization_id)
        limit = plan.limits.api_keys
        if limit is None:
            return
        used = await self._repo.count_api_keys(organization_id, now)
        if used + 1 > limit:
            raise limit_error(plan, "api_keys", used, limit)

    async def check_storage(self, organization_id: uuid.UUID, adding_bytes: int) -> None:
        """Raise unless a file of `adding_bytes` still fits in the plan's storage."""
        plan = await self.plan_for(organization_id)
        limit = plan.limits.storage_mb
        if limit is None:
            return
        used = await self._repo.stored_bytes(organization_id)
        if used + adding_bytes > limit * MB:
            raise limit_error(plan, "storage_mb", -(-used // MB), limit)

    async def summary(self, organization_id: uuid.UUID, *, now: datetime) -> list[UsageLine]:
        """Every limit with current usage (for Settings → Billing)."""
        plan = await self.plan_for(organization_id)
        return [
            UsageLine(
                "members",
                LABELS["members"],
                await self._repo.count_members(organization_id),
                plan.limits.members,
            ),
            UsageLine(
                "jobs_per_month",
                LABELS["jobs_per_month"],
                await self._repo.get_usage(organization_id, "jobs_per_month", month_start(now)),
                plan.limits.jobs_per_month,
            ),
            UsageLine(
                "api_keys",
                LABELS["api_keys"],
                await self._repo.count_api_keys(organization_id, now),
                plan.limits.api_keys,
            ),
            UsageLine(
                "storage_mb",
                LABELS["storage_mb"],
                -(-(await self._repo.stored_bytes(organization_id)) // MB),  # MB, rounded up
                plan.limits.storage_mb,
                unit="mb",
            ),
            UsageLine(
                "ai_requests_per_month",
                LABELS["ai_requests_per_month"],
                await self._repo.get_usage(
                    organization_id, "ai_requests_per_month", month_start(now)
                ),
                plan.limits.ai_requests_per_month,
            ),
        ]


class SyncUsageMeter:
    """Monthly metering for workers (sync database session, e.g. the LLM gateway).

    Each call runs in the caller's transaction; commit it right after, so the count is
    saved even if the rest of the work fails (the model call was paid for).
    """

    def __init__(self, session: Session, catalog: PlanCatalog) -> None:
        self._repo = SyncBillingRepository(session)
        self._catalog = catalog

    def plan_for(self, organization_id: uuid.UUID) -> PlanDefinition:
        """The plan whose limits apply right now."""
        return effective_plan(self._repo.get_subscription(organization_id), self._catalog)

    def consume(
        self,
        organization_id: uuid.UUID,
        metric: MeteredMetric,
        amount: int = 1,
        *,
        now: datetime | None = None,
    ) -> None:
        """Count, or raise LimitReachedError (nothing is counted)."""
        now = now or datetime.now(UTC)
        plan = self.plan_for(organization_id)
        limit = _limit(plan, metric)
        total = self._repo.add_usage(organization_id, metric, month_start(now), amount, limit=limit)
        if total is None:
            assert limit is not None
            used = self._repo.get_usage(organization_id, metric, month_start(now))
            raise limit_error(plan, metric, used, limit)

    def release(
        self,
        organization_id: uuid.UUID,
        metric: MeteredMetric,
        amount: int = 1,
        *,
        now: datetime | None = None,
    ) -> None:
        """Give back usage that did not happen (e.g. the model could not be reached)."""
        now = now or datetime.now(UTC)
        self._repo.release_usage(organization_id, metric, month_start(now), amount)
