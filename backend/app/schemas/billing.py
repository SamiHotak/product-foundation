"""Billing schemas: the public plan list, the workspace's plan and usage, checkout, portal."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class PlanLimitsOut(BaseModel):
    """What a workspace on this plan may use. null = unlimited."""

    members: int | None
    jobs_per_month: int | None
    api_keys: int | None
    storage_mb: int | None
    ai_requests_per_month: int | None


class PlanOut(BaseModel):
    """One plan as shown on the pricing page."""

    id: str
    name: str
    description: str
    price_monthly: int = Field(description="Cents per month when billed monthly.")
    price_yearly: int = Field(description="Cents per year when billed yearly.")
    trial_days: int
    highlighted: bool
    contact_sales: bool
    features: list[str]
    limits: PlanLimitsOut


class PlansResponse(BaseModel):
    """Everything the pricing page needs."""

    currency: Literal["eur", "usd", "gbp", "chf"]
    prices_include_vat: bool
    plans: list[PlanOut]


class CheckoutCreate(BaseModel):
    """Start paying for a plan."""

    plan_id: str = Field(min_length=1, max_length=32)
    interval: Literal["month", "year"] = "month"


class RedirectResponse(BaseModel):
    """Send the browser to this address (Stripe checkout or customer portal)."""

    url: str


class UsageItem(BaseModel):
    """One limit of the plan and how much of it is used."""

    metric: Literal["members", "jobs_per_month", "api_keys", "storage_mb", "ai_requests_per_month"]
    label: str
    used: int
    limit: int | None = Field(description="null = unlimited.")
    unit: Literal["count", "mb"] = Field(
        default="count", description='"mb": used and limit are megabytes (file storage).'
    )


class BillingOverview(BaseModel):
    """The workspace's plan, subscription and usage. Every member may read it."""

    provider: Literal["stripe", "dev", "none"] = Field(
        description='"none": paid plans are switched off. "dev": pretend checkout (local only).'
    )
    plan_id: str
    plan_name: str
    status: str | None = Field(
        description="Stripe status: trialing, active, past_due, canceled, ... null = never paid."
    )
    interval: Literal["month", "year"] | None
    current_period_end: datetime | None
    cancel_at_period_end: bool
    trial_end: datetime | None
    trial_available: bool = Field(description="False once this workspace used its free trial.")
    has_billing_account: bool = Field(description="True when the customer portal can be opened.")
    can_manage: bool = Field(description="The caller may change the plan (the owner).")
    usage: list[UsageItem]
    usage_resets_on: date = Field(description="Monthly counters start from 0 on this day (UTC).")


class DevSetPlan(BaseModel):
    """Local development / e2e only: put the workspace on a plan without paying."""

    plan_id: str = Field(min_length=1, max_length=32)
