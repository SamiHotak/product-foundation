"""Plan limits and usage metering.

The plan of a workspace = its paid subscription (while Stripe says trialing / active /
past_due), else the free plan. Limits come from app/core/plans.py through the catalog.

Three kinds of limits:
- metered per month   `consume()` adds to a counter in the same transaction as the work.
                      One SQL statement checks and adds, so parallel requests can't pass it.
- seats               `check_seats()` counts members + open invites (callers lock the org row).
- things you keep     `check_api_keys()` counts active keys (callers lock the org row).

When a limit is reached, `LimitReachedError` (HTTP 402, code "limit_reached") tells the
person what happened and that an upgrade helps. The UI shows an "See plans" link with it.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Literal

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.plans import PlanCatalog, PlanDefinition
from app.repositories.billing import BillingRepository

Metric = Literal["members", "jobs_per_month", "api_keys"]

LABELS: dict[str, str] = {
    "members": "People in this workspace",
    "jobs_per_month": "Background jobs this month",
    "api_keys": "API keys",
}


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


class UsageService:
    """Reads plans and limits, and meters usage. One instance per request."""

    def __init__(self, db: AsyncSession, catalog: PlanCatalog) -> None:
        self._repo = BillingRepository(db)
        self._catalog = catalog

    async def plan_for(self, organization_id: uuid.UUID) -> PlanDefinition:
        """The plan whose limits apply right now."""
        sub = await self._repo.get_subscription(organization_id)
        if sub is not None and sub.is_paid:
            plan = self._catalog.get(sub.plan_id)
            if plan is not None:
                return plan
        return self._catalog.free

    async def consume(
        self,
        organization_id: uuid.UUID,
        metric: Metric,
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
            raise self._error(plan, metric, used, limit)

    async def release(
        self,
        organization_id: uuid.UUID,
        metric: Metric,
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
            raise self._error(plan, "members", used, limit)

    async def check_api_keys(self, organization_id: uuid.UUID, *, now: datetime) -> None:
        """Raise unless one more API key fits."""
        plan = await self.plan_for(organization_id)
        limit = plan.limits.api_keys
        if limit is None:
            return
        used = await self._repo.count_api_keys(organization_id, now)
        if used + 1 > limit:
            raise self._error(plan, "api_keys", used, limit)

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
        ]

    def _error(self, plan: PlanDefinition, metric: str, used: int, limit: int) -> LimitReachedError:
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
