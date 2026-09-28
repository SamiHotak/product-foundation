"""Plans and prices: the ONE place each product defines what it sells.

The pricing section on the website reads these through `GET /api/billing/plans`, and phase 4A
uses the same list for Stripe checkout and for the usage limits. So the page can never promise
something different from what the app enforces.

Per product, change:
- the plans below (names, prices in cents, limits, feature lines),
- `CURRENCY` and `PRICES_INCLUDE_VAT`.

Prices are in the smallest unit (cents). `None` as a limit means "no limit".

Stripe: `make stripe-sync` creates the products and prices in your Stripe account from this
file (price lookup keys like "foundation_pro_month"). Run it again after changing a price.
Checkout refuses to start while Stripe's price differs from this file.

Limits (see app/services/usage.py):
- members          people in the workspace (open invites count too)
- jobs_per_month   metered background jobs per calendar month (UTC); GDPR exports never count
- api_keys         active API keys
When a workspace moves to a smaller plan, nothing is deleted: it just can't add more.
"""

from dataclasses import dataclass
from typing import Literal

Interval = Literal["month", "year"]

CURRENCY = "eur"

# Germany: prices shown to CONSUMERS must include VAT (PAngV). Selling only to businesses,
# you may show net prices with a clear "plus VAT" note. Ask your tax advisor which fits.
PRICES_INCLUDE_VAT = False


@dataclass(frozen=True)
class PlanLimits:
    """What a workspace on this plan may use. None = unlimited."""

    members: int | None
    jobs_per_month: int | None
    api_keys: int | None


@dataclass(frozen=True)
class PlanDefinition:
    """One plan as the product sells it."""

    id: str
    name: str
    description: str
    price_monthly: int  # cents per month, billed monthly
    price_yearly: int  # cents per year, billed yearly
    limits: PlanLimits
    features: tuple[str, ...]
    trial_days: int = 0
    highlighted: bool = False  # shown as the recommended plan
    contact_sales: bool = False  # no self-service checkout; "Contact us" instead
    public: bool = True  # False = exists (e.g. for old customers) but not on the website


PLANS: tuple[PlanDefinition, ...] = (
    PlanDefinition(
        id="free",
        name="Free",
        description="For trying it out on your own.",
        price_monthly=0,
        price_yearly=0,
        limits=PlanLimits(members=1, jobs_per_month=50, api_keys=1),
        features=(
            "1 person",
            "50 background jobs a month",
            "1 API key",
            "Data export at any time",
        ),
    ),
    PlanDefinition(
        id="pro",
        name="Pro",
        description="For a small team that uses it every day.",
        price_monthly=2900,
        price_yearly=29000,
        limits=PlanLimits(members=5, jobs_per_month=2000, api_keys=10),
        features=(
            "Up to 5 people",
            "2,000 background jobs a month",
            "10 API keys",
            "Audit log",
            "Email support",
        ),
        trial_days=14,
        highlighted=True,
    ),
    PlanDefinition(
        id="business",
        name="Business",
        description="For larger teams with extra needs.",
        price_monthly=9900,
        price_yearly=99000,
        limits=PlanLimits(members=None, jobs_per_month=20000, api_keys=None),
        features=(
            "Unlimited people",
            "20,000 background jobs a month",
            "Unlimited API keys",
            "Data processing agreement (AVV)",
            "Priority support",
        ),
        trial_days=14,
    ),
)


# The plan of every workspace without a paid subscription. Must exist and cost 0.
FREE_PLAN_ID = "free"


def get_plan(plan_id: str) -> PlanDefinition | None:
    """A plan by id (public or not), or None."""
    return next((p for p in PLANS if p.id == plan_id), None)


class PlanCatalog:
    """The plans a running app sells. Tests use a different catalog (e.g. roomier limits)."""

    def __init__(
        self, plans: tuple[PlanDefinition, ...] = PLANS, free_plan_id: str = FREE_PLAN_ID
    ) -> None:
        ids = [p.id for p in plans]
        if len(set(ids)) != len(ids):
            raise ValueError("Plan ids must be unique.")
        self.plans = plans
        free = self.get(free_plan_id)
        if free is None or free.price_monthly != 0 or free.price_yearly != 0:
            raise ValueError(f"The free plan {free_plan_id!r} must exist and cost 0.")
        self.free = free

    def get(self, plan_id: str | None) -> PlanDefinition | None:
        """A plan by id (public or not), or None."""
        return next((p for p in self.plans if p.id == plan_id), None)

    def sellable(self, plan_id: str) -> PlanDefinition | None:
        """A plan people can buy with self-service checkout, or None."""
        plan = self.get(plan_id)
        if plan is None or not plan.public or plan.contact_sales or plan.price_monthly <= 0:
            return None
        return plan

    @staticmethod
    def price(plan: PlanDefinition, interval: Interval) -> int:
        """Cents per interval."""
        return plan.price_monthly if interval == "month" else plan.price_yearly


DEFAULT_CATALOG = PlanCatalog()
