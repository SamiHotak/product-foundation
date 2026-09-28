"""Billing: each workspace's Stripe customer and subscription, usage counters, and the
Stripe events we already handled (so a repeated webhook is never applied twice).
"""

import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

# Stripe statuses that keep the paid plan. "past_due": Stripe is still retrying the card,
# so the customer keeps the plan for now (Stripe cancels it if all retries fail).
PAID_STATUSES = frozenset({"trialing", "active", "past_due"})
# Not ended yet (could still charge or become paid). "canceled" / "incomplete_expired" = ended.
LIVE_STATUSES = PAID_STATUSES | {"unpaid", "incomplete", "paused"}


class Subscription(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One row per workspace that ever started a checkout. No row = free plan.

    The data mirrors Stripe. Stripe is the source of truth; webhooks keep this copy fresh,
    so every request can read the plan without calling Stripe.
    """

    __tablename__ = "subscriptions"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), unique=True
    )
    stripe_customer_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    # The plan id from app/core/plans.py that the subscription pays for.
    plan_id: Mapped[str | None] = mapped_column(String(32))
    interval: Mapped[str | None] = mapped_column(String(8))  # "month" or "year"
    # Stripe's status: trialing, active, past_due, canceled, unpaid, incomplete, paused ...
    status: Mapped[str | None] = mapped_column(String(32))
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False)
    trial_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # One free trial per workspace, ever.
    trial_used: Mapped[bool] = mapped_column(Boolean, default=False)
    # The open Stripe Checkout (at most one: a new checkout expires the old one, so two
    # browser tabs can't create two subscriptions).
    checkout_session_id: Mapped[str | None] = mapped_column(String(255))

    @property
    def is_paid(self) -> bool:
        """True while the subscription gives the workspace its paid plan."""
        return self.status in PAID_STATUSES and self.plan_id is not None


class UsageRecord(Base):
    """How much of a metered limit a workspace used in one calendar month (UTC)."""

    __tablename__ = "usage_records"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    metric: Mapped[str] = mapped_column(String(32), primary_key=True)
    period_start: Mapped[date] = mapped_column(Date, primary_key=True)  # first day of the month
    count: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class StripeEvent(Base):
    """A Stripe webhook event we handled. The primary key makes handling idempotent."""

    __tablename__ = "stripe_events"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)  # "evt_..."
    type: Mapped[str] = mapped_column(String(100))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
