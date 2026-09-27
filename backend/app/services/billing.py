"""Billing. Phase 3B: the public plan list (from app/core/plans.py).

Phase 4A adds Stripe checkout, the customer portal, webhooks and usage limits here.
"""

from app.core import plans as plan_config
from app.schemas.billing import PlanLimitsOut, PlanOut, PlansResponse


class BillingService:
    """Plans and (from phase 4A) subscriptions."""

    def __init__(
        self,
        catalog: tuple[plan_config.PlanDefinition, ...] = plan_config.PLANS,
        *,
        currency: str = plan_config.CURRENCY,
        prices_include_vat: bool = plan_config.PRICES_INCLUDE_VAT,
    ) -> None:
        self._catalog = catalog
        self._currency = currency
        self._prices_include_vat = prices_include_vat

    def public_plans(self) -> PlansResponse:
        """The plans shown on the website, in the configured order."""
        return PlansResponse.model_validate(
            {
                "currency": self._currency,
                "prices_include_vat": self._prices_include_vat,
                "plans": [self._to_schema(p) for p in self._catalog if p.public],
            }
        )

    @staticmethod
    def _to_schema(plan: plan_config.PlanDefinition) -> PlanOut:
        return PlanOut(
            id=plan.id,
            name=plan.name,
            description=plan.description,
            price_monthly=plan.price_monthly,
            price_yearly=plan.price_yearly,
            trial_days=plan.trial_days,
            highlighted=plan.highlighted,
            contact_sales=plan.contact_sales,
            features=list(plan.features),
            limits=PlanLimitsOut(
                members=plan.limits.members,
                jobs_per_month=plan.limits.jobs_per_month,
                api_keys=plan.limits.api_keys,
            ),
        )
