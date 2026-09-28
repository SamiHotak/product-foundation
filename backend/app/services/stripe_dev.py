"""A pretend payment provider for local development and e2e tests (BILLING_DEV_TOOLS=true).

No Stripe account needed. "Checkout" and "portal" are tiny pages of our own API
(app/routers/billing_dev.py) that change the subscription through the SAME code path
the Stripe webhooks use (`BillingService.apply_snapshot`). Refused in production.
"""

import uuid
from typing import Literal

from app.core.config import Settings
from app.core.plans import Interval, PlanDefinition
from app.core.security import sign_data
from app.services.stripe_gateway import (
    CheckoutSession,
    InvalidWebhookError,
    SubscriptionSnapshot,
    WebhookEvent,
)

LINK_SECONDS = 3600


class DevGateway:
    """Hands out signed links to the pretend checkout / portal pages."""

    kind: Literal["stripe", "dev"] = "dev"

    def __init__(self, settings: Settings) -> None:
        self._secret = settings.secret_key.get_secret_value()
        self._app_url = settings.app_url
        # Relative links: they work from any address the app is opened at (e2e tests open
        # it as http://frontend:3000 inside Docker, people as http://localhost:3000).
        self._base = f"{settings.api_prefix}/billing/dev"

    def _relative(self, url: str) -> str:
        return url[len(self._app_url) :] or "/" if url.startswith(self._app_url) else url

    def sign(self, data: dict[str, str | int]) -> str:
        """A signed token for a dev page link."""
        return sign_data(data, self._secret, max_age_seconds=LINK_SECONDS)

    async def create_customer(self, *, organization_id: uuid.UUID, name: str, email: str) -> str:
        """A made-up customer id."""
        return f"cus_dev_{uuid.uuid4().hex[:20]}"

    async def create_checkout(
        self,
        *,
        customer_id: str,
        organization_id: uuid.UUID,
        plan: PlanDefinition,
        interval: Interval,
        trial_days: int,
        success_url: str,
        cancel_url: str,
    ) -> CheckoutSession:
        """Link to the pretend checkout page."""
        token = self.sign(
            {
                "customer_id": customer_id,
                "organization_id": str(organization_id),
                "plan_id": plan.id,
                "interval": interval,
                "trial_days": trial_days,
                "success_url": self._relative(success_url),
                "cancel_url": self._relative(cancel_url),
            }
        )
        return CheckoutSession(
            id=f"cs_dev_{uuid.uuid4().hex[:20]}", url=f"{self._base}/checkout?token={token}"
        )

    async def expire_checkout(self, session_id: str) -> None:
        """Pretend links simply time out after an hour."""

    async def create_portal(self, *, customer_id: str, return_url: str) -> str:
        """Link to the pretend customer portal."""
        token = self.sign({"customer_id": customer_id, "return_url": self._relative(return_url)})
        return f"{self._base}/portal?token={token}"

    async def get_subscription(self, subscription_id: str) -> SubscriptionSnapshot | None:
        """The dev provider keeps no data of its own."""
        return None

    async def live_subscriptions(self, customer_id: str) -> list[SubscriptionSnapshot]:
        """Our database is the only record in dev mode."""
        return []

    async def cancel_subscription(self, subscription_id: str) -> None:
        """Nothing to cancel anywhere."""

    def parse_event(self, payload: bytes, signature: str | None) -> WebhookEvent:
        """There are no webhooks in dev mode."""
        raise InvalidWebhookError("Webhooks are off in dev billing mode.")

    def delete_customer(self, customer_id: str) -> None:
        """Nothing to delete anywhere."""
