"""Billing schemas. Phase 3B: the public plan list. Phase 4A adds checkout and subscriptions."""

from typing import Literal

from pydantic import BaseModel, Field


class PlanLimitsOut(BaseModel):
    """What a workspace on this plan may use. null = unlimited."""

    members: int | None
    jobs_per_month: int | None
    api_keys: int | None


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
