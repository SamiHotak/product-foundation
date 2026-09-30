"""Billing queries: subscriptions, usage counters, handled Stripe events.

Every tenant query takes the organization id. Stripe webhooks find the workspace by the
Stripe customer id, which we created for exactly one workspace.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import Select, Update, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from sqlalchemy.sql.dml import ReturningInsert

from app.models.api_key import ApiKey
from app.models.billing import StripeEvent, Subscription, UsageRecord
from app.models.file import FileStatus, StoredFile
from app.models.invite import Invite
from app.models.organization import Membership, Role
from app.models.user import User


def usage_upsert(
    organization_id: uuid.UUID, metric: str, period_start: date, amount: int, limit: int | None
) -> ReturningInsert[tuple[int]]:
    """ONE statement that adds `amount` only while the total stays within `limit`.

    It returns the new total, or no row when the limit would be passed (nothing changes).
    Safe with many requests at once: Postgres locks the counter row during the update.
    """
    stmt = insert(UsageRecord).values(
        organization_id=organization_id, metric=metric, period_start=period_start, count=amount
    )
    where = (UsageRecord.count + stmt.excluded.count) <= limit if limit is not None else None
    return stmt.on_conflict_do_update(
        index_elements=[UsageRecord.organization_id, UsageRecord.metric, UsageRecord.period_start],
        set_={"count": UsageRecord.count + stmt.excluded.count, "updated_at": func.now()},
        where=where,
    ).returning(UsageRecord.count)


def usage_release(
    organization_id: uuid.UUID, metric: str, period_start: date, amount: int
) -> Update:
    """Give back usage (never below 0)."""
    return (
        update(UsageRecord)
        .where(
            UsageRecord.organization_id == organization_id,
            UsageRecord.metric == metric,
            UsageRecord.period_start == period_start,
        )
        .values(count=func.greatest(UsageRecord.count - amount, 0))
    )


def usage_get(organization_id: uuid.UUID, metric: str, period_start: date) -> Select[tuple[int]]:
    """Usage of one metric in one month."""
    return select(UsageRecord.count).where(
        UsageRecord.organization_id == organization_id,
        UsageRecord.metric == metric,
        UsageRecord.period_start == period_start,
    )


def subscription_of(organization_id: uuid.UUID) -> Select[tuple[Subscription]]:
    """The workspace's billing row."""
    return select(Subscription).where(Subscription.organization_id == organization_id)


def stored_bytes(organization_id: uuid.UUID) -> Select[tuple[int]]:
    """Bytes of all files that take space (uploads in progress count too)."""
    return select(func.coalesce(func.sum(StoredFile.size_bytes), 0)).where(
        StoredFile.organization_id == organization_id,
        StoredFile.status != FileStatus.REJECTED,
    )


class BillingRepository:
    """Async billing queries for the API."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- subscriptions --------------------------------------------------------------------

    async def get_subscription(
        self, organization_id: uuid.UUID, *, lock: bool = False
    ) -> Subscription | None:
        """The workspace's billing row, or None (= free, never checked out)."""
        query = subscription_of(organization_id)
        if lock:
            query = query.with_for_update()
        found: Subscription | None = await self._session.scalar(
            query.execution_options(populate_existing=True)
        )
        return found

    async def get_or_create_subscription(self, organization_id: uuid.UUID) -> Subscription:
        """The billing row, created if missing, locked until commit."""
        await self._session.execute(
            insert(Subscription)
            .values(
                id=uuid.uuid4(),
                organization_id=organization_id,
                cancel_at_period_end=False,
                trial_used=False,
            )
            .on_conflict_do_nothing(index_elements=[Subscription.organization_id])
        )
        found = await self.get_subscription(organization_id, lock=True)
        assert found is not None
        return found

    async def find_by_customer(self, customer_id: str, *, lock: bool = True) -> Subscription | None:
        """The billing row of a Stripe customer (locked until commit, unless lock=False)."""
        query = select(Subscription).where(Subscription.stripe_customer_id == customer_id)
        if lock:
            query = query.with_for_update()
        found: Subscription | None = await self._session.scalar(
            query.execution_options(populate_existing=True)
        )
        return found

    async def owner(self, organization_id: uuid.UUID) -> User | None:
        """The workspace owner (billing emails go to them)."""
        found: User | None = await self._session.scalar(
            select(User)
            .join(Membership, Membership.user_id == User.id)
            .where(Membership.organization_id == organization_id, Membership.role == Role.OWNER)
        )
        return found

    # --- counts for limits ----------------------------------------------------------------

    async def count_members(self, organization_id: uuid.UUID) -> int:
        """People in the workspace."""
        return int(
            await self._session.scalar(
                select(func.count())
                .select_from(Membership)
                .where(Membership.organization_id == organization_id)
            )
            or 0
        )

    async def count_open_invites(
        self, organization_id: uuid.UUID, now: datetime, *, except_email: str | None = None
    ) -> int:
        """Invites nobody accepted yet that still work (they will take a seat)."""
        query = (
            select(func.count())
            .select_from(Invite)
            .where(
                Invite.organization_id == organization_id,
                Invite.accepted_at.is_(None),
                Invite.revoked_at.is_(None),
                Invite.expires_at > now,
            )
        )
        if except_email is not None:
            query = query.where(func.lower(Invite.email) != except_email.lower())
        return int(await self._session.scalar(query) or 0)

    async def count_api_keys(self, organization_id: uuid.UUID, now: datetime) -> int:
        """Keys that work (not revoked, not expired)."""
        return int(
            await self._session.scalar(
                select(func.count())
                .select_from(ApiKey)
                .where(
                    ApiKey.organization_id == organization_id,
                    ApiKey.revoked_at.is_(None),
                    (ApiKey.expires_at.is_(None)) | (ApiKey.expires_at > now),
                )
            )
            or 0
        )

    # --- metered usage --------------------------------------------------------------------

    async def add_usage(
        self,
        organization_id: uuid.UUID,
        metric: str,
        period_start: date,
        amount: int,
        *,
        limit: int | None,
    ) -> int | None:
        """Add `amount` in ONE statement, only if the total stays within `limit`.

        Returns the new total, or None when the limit would be passed (nothing changes).
        """
        if limit is not None and amount > limit:
            return None
        total = await self._session.scalar(
            usage_upsert(organization_id, metric, period_start, amount, limit)
        )
        return int(total) if total is not None else None

    async def release_usage(
        self, organization_id: uuid.UUID, metric: str, period_start: date, amount: int
    ) -> None:
        """Give back usage that did not happen (e.g. the job could not be queued)."""
        await self._session.execute(usage_release(organization_id, metric, period_start, amount))

    async def get_usage(self, organization_id: uuid.UUID, metric: str, period_start: date) -> int:
        """Usage of one metric in one month."""
        value = await self._session.scalar(usage_get(organization_id, metric, period_start))
        return int(value or 0)

    async def stored_bytes(self, organization_id: uuid.UUID) -> int:
        """Bytes of the workspace's files (uploads in progress count too)."""
        return int(await self._session.scalar(stored_bytes(organization_id)) or 0)

    # --- Stripe events --------------------------------------------------------------------

    async def claim_event(self, event_id: str, event_type: str) -> bool:
        """Remember the event. False if it was handled before (then do nothing)."""
        inserted = await self._session.scalar(
            insert(StripeEvent)
            .values(id=event_id, type=event_type)
            .on_conflict_do_nothing(index_elements=[StripeEvent.id])
            .returning(StripeEvent.id)
        )
        return inserted is not None


class SyncBillingRepository:
    """Sync billing queries for workers (nightly jobs, the LLM gateway)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_subscription(self, organization_id: uuid.UUID) -> Subscription | None:
        """The workspace's billing row, or None."""
        found: Subscription | None = self._session.scalar(subscription_of(organization_id))
        return found

    def add_usage(
        self,
        organization_id: uuid.UUID,
        metric: str,
        period_start: date,
        amount: int,
        *,
        limit: int | None,
    ) -> int | None:
        """Same as the async version: the new total, or None when over the limit."""
        if limit is not None and amount > limit:
            return None
        total = self._session.scalar(
            usage_upsert(organization_id, metric, period_start, amount, limit)
        )
        return int(total) if total is not None else None

    def release_usage(
        self, organization_id: uuid.UUID, metric: str, period_start: date, amount: int
    ) -> None:
        """Give back usage."""
        self._session.execute(usage_release(organization_id, metric, period_start, amount))

    def get_usage(self, organization_id: uuid.UUID, metric: str, period_start: date) -> int:
        """Usage of one metric in one month."""
        return int(self._session.scalar(usage_get(organization_id, metric, period_start)) or 0)

    def customer_id(self, organization_id: uuid.UUID) -> str | None:
        """The workspace's Stripe customer, if it ever started a checkout."""
        value = self._session.scalar(
            select(Subscription.stripe_customer_id).where(
                Subscription.organization_id == organization_id
            )
        )
        return value if isinstance(value, str) else None

    def delete_old_events(self, before: datetime) -> int:
        """Handled webhook ids older than Stripe's retry window are not needed any more."""
        result = self._session.execute(delete(StripeEvent).where(StripeEvent.received_at < before))
        return int(getattr(result, "rowcount", 0))
