"""Everything that talks to Stripe, behind one small interface (`PaymentGateway`).

- `StripeGateway`   the real Stripe API (test mode or live, depending on the key).
- `DevGateway`      (app/services/stripe_dev.py) a pretend checkout for local work and e2e tests.
- Tests use `tests.fakes.FakeGateway`.

Stripe objects are turned into small dataclasses here, so the rest of the app never
depends on Stripe's object shapes (they change between API versions).
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

import stripe

from app.core.config import Settings
from app.core.errors import AppError, ServiceUnavailableError
from app.core.logging import get_logger
from app.core.plans import CURRENCY, Interval, PlanCatalog, PlanDefinition
from app.models.billing import LIVE_STATUSES

logger = get_logger(__name__)

CHECKOUT_UNAVAILABLE = "Checkout is not available right now. Please try again in a few minutes."


class InvalidWebhookError(AppError):
    """The webhook body or signature is not from Stripe."""

    code = "invalid_webhook"


class PaymentProviderError(ServiceUnavailableError):
    """Stripe could not be reached or refused the request (details are logged, not shown)."""

    code = "payment_provider_error"


def lookup_key(prefix: str, plan_id: str, interval: str) -> str:
    """Stripe price lookup key, e.g. "foundation_pro_month"."""
    return f"{prefix}_{plan_id}_{interval}"


def product_id(prefix: str, plan_id: str) -> str:
    """Stripe product id, e.g. "foundation_pro"."""
    return f"{prefix}_{plan_id}"


@dataclass(frozen=True)
class SubscriptionSnapshot:
    """The parts of a Stripe subscription the app needs."""

    id: str
    customer_id: str
    status: str
    plan_id: str | None  # None: a price that is not one of this product's plans
    interval: str | None
    current_period_end: datetime | None
    cancel_at_period_end: bool
    trial_end: datetime | None
    organization_id: str | None = None  # from the subscription metadata


@dataclass(frozen=True)
class CheckoutSession:
    """A hosted checkout page."""

    id: str
    url: str


@dataclass(frozen=True)
class WebhookEvent:
    """A verified Stripe event."""

    id: str
    type: str
    data: dict[str, Any] = field(default_factory=dict)  # event.data.object as plain dicts

    @property
    def customer_id(self) -> str | None:
        """The Stripe customer the event is about."""
        value = self.data.get("customer")
        if isinstance(value, dict):
            value = value.get("id")
        return value if isinstance(value, str) else None

    @property
    def subscription_id(self) -> str | None:
        """The subscription the event is about (subscription, checkout or invoice events)."""
        obj = self.data
        if obj.get("object") == "subscription":
            return _str(obj.get("id"))
        direct = obj.get("subscription")
        if isinstance(direct, dict):
            direct = direct.get("id")
        if isinstance(direct, str):
            return direct
        # Invoices (API 2025+): parent.subscription_details.subscription
        parent = obj.get("parent") or {}
        details = parent.get("subscription_details") or {} if isinstance(parent, dict) else {}
        nested = details.get("subscription") if isinstance(details, dict) else None
        if isinstance(nested, dict):
            nested = nested.get("id")
        return nested if isinstance(nested, str) else None


def _str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def app_of(metadata: Any) -> str | None:
    """The "app" metadata value (Stripe objects are NOT dicts: no .get())."""
    if metadata is None:
        return None
    data = metadata.to_dict() if hasattr(metadata, "to_dict") else metadata
    value = data.get("app") if isinstance(data, dict) else None
    return value if isinstance(value, str) else None


def _when(value: Any) -> datetime | None:
    return datetime.fromtimestamp(int(value), tz=UTC) if isinstance(value, int | float) else None


def snapshot_from_stripe(obj: dict[str, Any], prefix: str) -> SubscriptionSnapshot:
    """Turn a Stripe subscription (as a dict) into a snapshot."""
    items = (obj.get("items") or {}).get("data") or []
    item: dict[str, Any] = items[0] if items else {}
    price: dict[str, Any] = item.get("price") or {}
    meta = price.get("metadata") or {}
    plan_id: str | None = None
    if meta.get("app") == prefix and isinstance(meta.get("plan_id"), str):
        plan_id = meta["plan_id"]
    else:
        key = price.get("lookup_key")
        if isinstance(key, str) and key.startswith(f"{prefix}_"):
            plan_id = key[len(prefix) + 1 :].rsplit("_", 1)[0] or None
    recurring = price.get("recurring") or {}
    customer = obj.get("customer")
    if isinstance(customer, dict):
        customer = customer.get("id")
    return SubscriptionSnapshot(
        id=str(obj["id"]),
        customer_id=str(customer),
        status=str(obj.get("status")),
        plan_id=plan_id,
        interval=_str(recurring.get("interval")),
        # Since API 2025-03-31 the period lives on the subscription item.
        current_period_end=_when(item.get("current_period_end"))
        or _when(obj.get("current_period_end")),
        cancel_at_period_end=bool(obj.get("cancel_at_period_end")) or bool(obj.get("cancel_at")),
        trial_end=_when(obj.get("trial_end")),
        organization_id=_str((obj.get("metadata") or {}).get("organization_id")),
    )


class PaymentGateway(Protocol):
    """What billing needs from a payment provider."""

    kind: Literal["stripe", "dev"]

    async def create_customer(self, *, organization_id: uuid.UUID, name: str, email: str) -> str:
        """Create a customer for the workspace; returns its id."""
        ...

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
        """Start a hosted checkout (send the browser to its URL)."""
        ...

    async def expire_checkout(self, session_id: str) -> None:
        """Close an open checkout so it can't be paid any more (no error if already done)."""
        ...

    async def create_portal(self, *, customer_id: str, return_url: str) -> str:
        """Open the hosted customer portal; returns its URL."""
        ...

    async def get_subscription(self, subscription_id: str) -> SubscriptionSnapshot | None:
        """The subscription as Stripe has it NOW (None if it does not exist)."""
        ...

    async def live_subscriptions(self, customer_id: str) -> list[SubscriptionSnapshot]:
        """The customer's subscriptions that have not ended (Stripe's view, not ours)."""
        ...

    async def cancel_subscription(self, subscription_id: str) -> None:
        """End a subscription now (no error if it is already gone)."""
        ...

    def parse_event(self, payload: bytes, signature: str | None) -> WebhookEvent:
        """Verify the signature and return the event (raise InvalidWebhookError)."""
        ...

    def delete_customer(self, customer_id: str) -> None:
        """Delete the customer: ends ALL its subscriptions at once (no refund) and removes
        the personal data (GDPR). Used when a workspace is deleted. Sync (nightly job)."""
        ...


class StripeGateway:
    """The real Stripe API. One instance per process (it keeps an HTTP connection pool)."""

    kind: Literal["stripe", "dev"] = "stripe"

    def __init__(
        self,
        settings: Settings,
        catalog: PlanCatalog,
        *,
        http_client: stripe.HTTPClient | None = None,
    ) -> None:
        assert settings.stripe_secret_key is not None
        self._settings = settings
        self._catalog = catalog
        self._prefix = settings.stripe_prefix
        self._client = stripe.StripeClient(
            settings.stripe_secret_key.get_secret_value(),
            http_client=http_client or stripe.HTTPXClient(timeout=20, allow_sync_methods=True),
            max_network_retries=2,
        )
        self._portal_config: str | None = None
        self._portal_config_loaded = False

    def _meta(self, organization_id: uuid.UUID) -> dict[str, str]:
        return {"organization_id": str(organization_id), "app": self._prefix}

    @staticmethod
    def _fail(action: str, exc: stripe.StripeError) -> PaymentProviderError:
        # Log the Stripe error for us; show a calm message to the customer.
        logger.error(
            "stripe_error",
            action=action,
            error_type=type(exc).__name__,
            code=getattr(exc, "code", None),
            message=str(getattr(exc, "user_message", None) or exc)[:300],
        )
        return PaymentProviderError(CHECKOUT_UNAVAILABLE)

    async def create_customer(self, *, organization_id: uuid.UUID, name: str, email: str) -> str:
        """One Stripe customer per workspace (an idempotency key stops duplicates)."""
        try:
            customer = await self._client.v1.customers.create_async(
                params={"name": name, "email": email, "metadata": self._meta(organization_id)},
                options={"idempotency_key": f"{self._prefix}-customer-{organization_id}"},
            )
        except stripe.StripeError as exc:
            raise self._fail("create_customer", exc) from exc
        return str(customer.id)

    async def _price_id(self, plan: PlanDefinition, interval: Interval) -> str:
        """The Stripe price for this plan, checked against plans.py."""
        key = lookup_key(self._prefix, plan.id, interval)
        try:
            prices = await self._client.v1.prices.list_async(
                params={"lookup_keys": [key], "active": True, "limit": 1}
            )
        except stripe.StripeError as exc:
            raise self._fail("find_price", exc) from exc
        expected = PlanCatalog.price(plan, interval)
        found = prices.data[0] if prices.data else None
        if found is None or found.unit_amount != expected or found.currency != CURRENCY:
            logger.error(
                "stripe_price_out_of_sync",
                lookup_key=key,
                expected=expected,
                found=getattr(found, "unit_amount", None),
                hint="run `make stripe-sync`",
            )
            raise PaymentProviderError(CHECKOUT_UNAVAILABLE)
        return str(found.id)

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
        """Stripe Checkout for a subscription. B2B: billing address and VAT ID are asked."""
        price_id = await self._price_id(plan, interval)
        subscription_data: dict[str, Any] = {"metadata": self._meta(organization_id)}
        if trial_days > 0:
            subscription_data["trial_period_days"] = trial_days
            # No card at the end of the trial = the subscription ends (never a surprise bill).
            subscription_data["trial_settings"] = {
                "end_behavior": {"missing_payment_method": "cancel"}
            }
        params: dict[str, Any] = {
            "mode": "subscription",
            "customer": customer_id,
            "client_reference_id": str(organization_id),
            "line_items": [{"price": price_id, "quantity": 1}],
            "success_url": success_url,
            "cancel_url": cancel_url,
            "subscription_data": subscription_data,
            "metadata": self._meta(organization_id),
            "billing_address_collection": "required",
            "customer_update": {"address": "auto", "name": "auto"},
            "tax_id_collection": {"enabled": True},
            "allow_promotion_codes": True,
            "automatic_tax": {"enabled": self._settings.stripe_automatic_tax},
        }
        try:
            session = await self._client.v1.checkout.sessions.create_async(
                params=params  # type: ignore[arg-type]
            )
        except stripe.StripeError as exc:
            raise self._fail("create_checkout", exc) from exc
        assert session.url
        return CheckoutSession(id=str(session.id), url=str(session.url))

    async def expire_checkout(self, session_id: str) -> None:
        """Expire an open checkout. Stripe refuses for finished ones: that is fine."""
        try:
            await self._client.v1.checkout.sessions.expire_async(session_id)
        except stripe.InvalidRequestError:
            return  # already completed or expired
        except stripe.StripeError as exc:
            raise self._fail("expire_checkout", exc) from exc

    async def _portal_configuration(self) -> str | None:
        """The portal settings `make stripe-sync` created for this product (else the default)."""
        if not self._portal_config_loaded:
            configs = await self._client.v1.billing_portal.configurations.list_async(
                params={"active": True, "limit": 100}
            )
            mine = [c for c in configs.data if app_of(c.metadata) == self._prefix]
            self._portal_config = str(mine[0].id) if mine else None
            self._portal_config_loaded = True
        return self._portal_config

    async def create_portal(self, *, customer_id: str, return_url: str) -> str:
        """Stripe's customer portal: card, invoices, VAT ID, change plan, cancel."""
        try:
            params: dict[str, Any] = {"customer": customer_id, "return_url": return_url}
            config = await self._portal_configuration()
            if config:
                params["configuration"] = config
            session = await self._client.v1.billing_portal.sessions.create_async(
                params=params  # type: ignore[arg-type]
            )
        except stripe.StripeError as exc:
            raise self._fail("create_portal", exc) from exc
        return str(session.url)

    async def get_subscription(self, subscription_id: str) -> SubscriptionSnapshot | None:
        """Read the subscription fresh from Stripe (webhooks can arrive out of order)."""
        try:
            sub = await self._client.v1.subscriptions.retrieve_async(subscription_id)
        except stripe.InvalidRequestError as exc:
            if exc.code == "resource_missing":
                return None
            raise self._fail("get_subscription", exc) from exc
        except stripe.StripeError as exc:
            raise self._fail("get_subscription", exc) from exc
        return snapshot_from_stripe(sub.to_dict(), self._prefix)

    async def live_subscriptions(self, customer_id: str) -> list[SubscriptionSnapshot]:
        """Every subscription of the customer that has not ended."""
        try:
            subs = await self._client.v1.subscriptions.list_async(
                params={"customer": customer_id, "status": "all", "limit": 20}
            )
        except stripe.StripeError as exc:
            raise self._fail("list_subscriptions", exc) from exc
        snaps = [snapshot_from_stripe(sub.to_dict(), self._prefix) for sub in subs.data]
        return [s for s in snaps if s.status in LIVE_STATUSES]

    async def cancel_subscription(self, subscription_id: str) -> None:
        """End a subscription now."""
        try:
            await self._client.v1.subscriptions.cancel_async(subscription_id)
        except stripe.InvalidRequestError as exc:
            if exc.code == "resource_missing":
                return
            raise self._fail("cancel_subscription", exc) from exc
        except stripe.StripeError as exc:
            raise self._fail("cancel_subscription", exc) from exc

    def parse_event(self, payload: bytes, signature: str | None) -> WebhookEvent:
        """Check the Stripe-Signature header with STRIPE_WEBHOOK_SECRET."""
        secret = self._settings.stripe_webhook_secret
        if secret is None or not signature:
            raise InvalidWebhookError("Missing webhook signature.")
        try:
            event = stripe.Webhook.construct_event(payload, signature, secret.get_secret_value())
        except (stripe.SignatureVerificationError, ValueError) as exc:
            raise InvalidWebhookError("Invalid webhook signature.") from exc
        obj = event.data.object
        return WebhookEvent(id=str(event.id), type=str(event.type), data=obj.to_dict())

    def delete_customer(self, customer_id: str) -> None:
        """Delete the customer (sync: used by the nightly deletion job).

        Stripe then ends all its subscriptions at once and keeps only what tax law needs
        (the invoices). Raises on other errors, so the deletion is retried the next night.
        """
        try:
            self._client.v1.customers.delete(customer_id)
        except stripe.InvalidRequestError as exc:
            if exc.code == "resource_missing":
                return  # already gone


_gateways: dict[str, PaymentGateway] = {}


def gateway_for(settings: Settings, catalog: PlanCatalog) -> PaymentGateway | None:
    """The gateway for these settings (cached per process), or None when billing is off."""
    if settings.stripe_enabled:
        key = f"stripe:{settings.stripe_prefix}"
        if key not in _gateways:
            _gateways[key] = StripeGateway(settings, catalog)
        return _gateways[key]
    if settings.billing_dev_tools:
        from app.services.stripe_dev import DevGateway

        return DevGateway(settings)
    return None


__all__ = [
    "CheckoutSession",
    "InvalidWebhookError",
    "PaymentGateway",
    "PaymentProviderError",
    "StripeGateway",
    "SubscriptionSnapshot",
    "WebhookEvent",
    "gateway_for",
    "lookup_key",
    "product_id",
    "snapshot_from_stripe",
]
