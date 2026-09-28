"""Billing: plans, Stripe checkout, the customer portal, and Stripe webhooks.

How a workspace gets a paid plan:
1. The owner picks a plan -> `start_checkout()` creates (once) a Stripe customer for the
   workspace and a Stripe Checkout page -> the browser goes there and pays.
2. Stripe sends webhooks -> `handle_webhook()` verifies the signature, skips events it has
   seen (idempotent), reads the subscription FRESH from Stripe (so the order of events does
   not matter) and saves it with `apply_snapshot()`.
3. Limits use the new plan from the next request on (app/services/usage.py).
Changing plan, card, VAT ID, invoices and cancelling happen in Stripe's customer portal.

Stripe is the source of truth; the `subscriptions` table is our fast copy of it.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import plans as plan_config
from app.core.config import Settings
from app.core.errors import AppError, ConflictError, NotFoundError, ServiceUnavailableError
from app.core.logging import get_logger
from app.core.permissions import Permission
from app.core.plans import Interval, PlanCatalog, PlanDefinition
from app.models.billing import LIVE_STATUSES, PAID_STATUSES, Subscription
from app.repositories.billing import BillingRepository
from app.repositories.organizations import OrganizationRepository
from app.schemas.billing import (
    BillingOverview,
    PlanLimitsOut,
    PlanOut,
    PlansResponse,
    RedirectResponse,
    UsageItem,
)
from app.services import email as emails
from app.services.audit import SYSTEM_FLAG, AuditAction, AuditService
from app.services.email import EmailMessage, EmailSender
from app.services.organizations import OrgContext
from app.services.stripe_gateway import PaymentGateway, SubscriptionSnapshot, WebhookEvent
from app.services.usage import UsageService, next_month_start

logger = get_logger(__name__)

PAYMENTS_OFF = "Paid plans are not available yet."
ALREADY_PAID = "This workspace already has a paid plan. Use “Manage billing” to change it."

# Webhook events we act on. Configure exactly these in the Stripe dashboard (docs/BILLING.md).
HANDLED_EVENTS = frozenset(
    {
        "checkout.session.completed",
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
        "customer.subscription.paused",
        "customer.subscription.resumed",
        "customer.subscription.trial_will_end",
        "invoice.paid",
        "invoice.payment_failed",
    }
)


class InvalidPlanError(AppError):
    """This plan can't be bought with self-service checkout."""

    code = "invalid_plan"


def _plan_out(plan: PlanDefinition) -> PlanOut:
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


def public_plans(
    catalog: tuple[PlanDefinition, ...] = plan_config.PLANS,
    *,
    currency: str = plan_config.CURRENCY,
    prices_include_vat: bool = plan_config.PRICES_INCLUDE_VAT,
) -> PlansResponse:
    """The plans shown on the website, in the configured order."""
    return PlansResponse.model_validate(
        {
            "currency": currency,
            "prices_include_vat": prices_include_vat,
            "plans": [_plan_out(p) for p in catalog if p.public],
        }
    )


def _date(value: datetime | None) -> str:
    return value.strftime("%-d %B %Y") if value else ""


class BillingService:
    """Plan, checkout, portal and webhooks for one request."""

    def __init__(
        self,
        db: AsyncSession,
        settings: Settings,
        catalog: PlanCatalog,
        gateway: PaymentGateway | None,
        email_sender: EmailSender,
        audit: AuditService,
    ) -> None:
        self._db = db
        self._settings = settings
        self._catalog = catalog
        self._gateway = gateway
        self._email = email_sender
        self._audit = audit
        self._repo = BillingRepository(db)
        self._usage = UsageService(db, catalog)
        self._pending: list[EmailMessage] = []  # sent after the commit

    @property
    def _billing_url(self) -> str:
        return f"{self._settings.app_url}/settings/billing"

    def _require_gateway(self) -> PaymentGateway:
        if self._gateway is None:
            raise ServiceUnavailableError(PAYMENTS_OFF)
        return self._gateway

    def _effective(self, sub: Subscription | None) -> PlanDefinition:
        if sub is not None and sub.is_paid:
            return self._catalog.get(sub.plan_id) or self._catalog.free
        return self._catalog.free

    # --- reading --------------------------------------------------------------------------

    async def overview(self, ctx: OrgContext) -> BillingOverview:
        """Plan, subscription and usage of the active workspace."""
        now = datetime.now(UTC)
        org_id = ctx.organization.id
        sub = await self._repo.get_subscription(org_id)
        plan = self._effective(sub)
        paid = sub is not None and sub.is_paid
        interval: Any = sub.interval if paid and sub else None
        return BillingOverview(
            provider=self._gateway.kind if self._gateway else "none",
            plan_id=plan.id,
            plan_name=plan.name,
            status=sub.status if sub else None,
            interval=interval,
            current_period_end=sub.current_period_end if paid and sub else None,
            cancel_at_period_end=bool(paid and sub and sub.cancel_at_period_end),
            trial_end=sub.trial_end if paid and sub and sub.status == "trialing" else None,
            trial_available=not (sub and sub.trial_used),
            has_billing_account=bool(sub and sub.stripe_customer_id),
            can_manage=ctx.can(Permission.BILLING_MANAGE),
            usage=[
                UsageItem.model_validate(line, from_attributes=True)
                for line in await self._usage.summary(org_id, now=now)
            ],
            usage_resets_on=next_month_start(now),
        )

    # --- checkout and portal (owner) ------------------------------------------------------

    async def start_checkout(
        self, ctx: OrgContext, plan_id: str, interval: Interval
    ) -> RedirectResponse:
        """A Stripe Checkout page for this plan. Only for workspaces without a paid plan."""
        ctx.require(Permission.BILLING_MANAGE)
        gateway = self._require_gateway()
        plan = self._catalog.sellable(plan_id)
        if plan is None or PlanCatalog.price(plan, interval) <= 0:
            raise InvalidPlanError("This plan can't be bought here. Choose another plan.")
        org_id = ctx.organization.id
        sub = await self._repo.get_or_create_subscription(org_id)  # locked until commit
        if sub.is_paid:
            raise ConflictError(ALREADY_PAID)
        if sub.stripe_customer_id is None:
            sub.stripe_customer_id = await gateway.create_customer(
                organization_id=org_id, name=ctx.organization.name, email=ctx.user.email
            )
        else:
            await self._settle_old_subscriptions(gateway, sub)
        if sub.checkout_session_id:
            # Only ONE open checkout: a second browser tab can't create a second subscription.
            await gateway.expire_checkout(sub.checkout_session_id)
        trial_days = 0 if sub.trial_used else plan.trial_days
        session = await gateway.create_checkout(
            customer_id=sub.stripe_customer_id,
            organization_id=org_id,
            plan=plan,
            interval=interval,
            trial_days=trial_days,
            success_url=f"{self._billing_url}?checkout=success",
            cancel_url=f"{self._billing_url}?checkout=cancelled",
        )
        sub.checkout_session_id = session.id
        await self._audit.record(
            AuditAction.BILLING_CHECKOUT_STARTED,
            organization_id=org_id,
            actor_user_id=ctx.user.id,
            details={"plan": plan.id, "interval": interval, "trial_days": trial_days},
        )
        await self._db.commit()
        logger.info("checkout_started", organization_id=str(org_id), plan=plan.id)
        return RedirectResponse(url=session.url)

    async def _settle_old_subscriptions(self, gateway: PaymentGateway, sub: Subscription) -> None:
        """Before a new checkout, look at what Stripe has for this customer (not our copy).

        A subscription that still gives a plan -> refuse (our copy was out of date; fix it).
        One that gives no plan but has not ended (unpaid, incomplete, paused) -> end it, so it
        can never come back to life next to the new one.
        """
        for old in await gateway.live_subscriptions(sub.stripe_customer_id or ""):
            if old.status in PAID_STATUSES:
                await self.apply_snapshot(old)
                await self._db.commit()
                await self._send_pending()
                raise ConflictError(ALREADY_PAID)
            await gateway.cancel_subscription(old.id)
            logger.info("old_subscription_cancelled", subscription_id=old.id, status=old.status)

    async def open_portal(self, ctx: OrgContext) -> RedirectResponse:
        """Stripe's customer portal: card, invoices, VAT ID, change plan, cancel."""
        ctx.require(Permission.BILLING_MANAGE)
        gateway = self._require_gateway()
        sub = await self._repo.get_subscription(ctx.organization.id)
        if sub is None or sub.stripe_customer_id is None:
            raise NotFoundError("There is no billing account yet. Choose a plan first.")
        url = await gateway.create_portal(
            customer_id=sub.stripe_customer_id, return_url=self._billing_url
        )
        return RedirectResponse(url=url)

    # --- webhooks -------------------------------------------------------------------------

    async def handle_webhook(self, payload: bytes, signature: str | None) -> str:
        """Verify, deduplicate and apply one Stripe event. Returns what happened (for logs).

        Raises on temporary problems (Stripe or the database unreachable): the endpoint then
        answers 5xx and Stripe sends the event again later. The event id is only stored
        together with its changes, so a failed attempt is retried in full.
        """
        gateway = self._require_gateway()
        event = gateway.parse_event(payload, signature)
        if event.type not in HANDLED_EVENTS:
            return "ignored"
        if not await self._repo.claim_event(event.id, event.type):
            await self._db.rollback()
            return "duplicate"
        outcome = await self._dispatch(gateway, event)
        await self._db.commit()
        await self._send_pending()
        logger.info("stripe_event", event_id=event.id, type=event.type, outcome=outcome)
        return outcome

    async def _dispatch(self, gateway: PaymentGateway, event: WebhookEvent) -> str:
        sub_id, customer_id = event.subscription_id, event.customer_id
        if sub_id is None or customer_id is None:
            return "no_subscription"
        # Lock our row BEFORE asking Stripe. Otherwise a slow event could read Stripe, wait,
        # and then overwrite what a newer event saved in the meantime.
        sub = await self._repo.find_by_customer(customer_id)
        if sub is None:
            logger.info("stripe_unknown_customer", subscription_id=sub_id)
            return "unknown_customer"  # e.g. another product in the same Stripe account
        if event.type == "checkout.session.completed" and event.data.get("id") == (
            sub.checkout_session_id
        ):
            sub.checkout_session_id = None
        snapshot = await gateway.get_subscription(sub_id)
        if snapshot is None:
            return "subscription_missing"
        outcome = await self.apply_snapshot(snapshot)
        if outcome != "applied":
            return outcome  # e.g. an old subscription: no emails about it
        if event.type == "invoice.payment_failed" and sub.is_paid:
            await self._queue_owner_email(sub.organization_id, "payment_failed", sub)
        if event.type == "customer.subscription.trial_will_end" and snapshot.status == "trialing":
            await self._queue_owner_email(sub.organization_id, "trial_ending", sub)
        return outcome

    # --- the one place that changes a subscription ----------------------------------------

    async def apply_snapshot(self, snap: SubscriptionSnapshot) -> str:
        """Save Stripe's current state of a subscription. Used by webhooks AND dev tools."""
        sub = await self._repo.find_by_customer(snap.customer_id)
        if sub is None:
            # Not one of our workspaces: e.g. another product that shares the Stripe account.
            logger.info("stripe_unknown_customer", subscription_id=snap.id)
            return "unknown_customer"
        current_id = sub.stripe_subscription_id
        if current_id is not None and current_id != snap.id:
            # A DIFFERENT subscription than the one we have. Only a live one may take over:
            if snap.status not in LIVE_STATUSES:
                return "stale_subscription"  # an old, ended one
            if sub.is_paid:
                if snap.status not in PAID_STATUSES:
                    return "stale_subscription"  # never swap a paid plan for an unpaid one
                gw = self._gateway
                current = await gw.get_subscription(current_id) if gw else None
                if current is not None and current.status in PAID_STATUSES:
                    # Two paying subscriptions: checkout prevents this, so it needs a human.
                    logger.error(
                        "second_paid_subscription",
                        kept=current_id,
                        other=snap.id,
                        hint="cancel and refund the other one in the Stripe dashboard",
                    )
                    return "second_subscription"
        if snap.plan_id is not None and self._catalog.get(snap.plan_id) is None:
            logger.error("stripe_unknown_plan", subscription_id=snap.id, plan=snap.plan_id)
        before = self._effective(sub)
        was_cancelling = sub.is_paid and sub.cancel_at_period_end
        sub.stripe_subscription_id = snap.id
        sub.plan_id = snap.plan_id
        sub.interval = snap.interval
        sub.status = snap.status
        sub.current_period_end = snap.current_period_end
        sub.cancel_at_period_end = snap.cancel_at_period_end
        sub.trial_end = snap.trial_end
        if snap.trial_end is not None or snap.status == "trialing":
            sub.trial_used = True
        after = self._effective(sub)
        org_id = sub.organization_id
        if before.id != after.id:
            await self._audit.record(
                AuditAction.BILLING_PLAN_CHANGED,
                organization_id=org_id,
                details={
                    SYSTEM_FLAG: True,
                    "from": before.name,
                    "to": after.name,
                    "status": snap.status,
                },
            )
            if before.id == self._catalog.free.id:
                await self._queue_owner_email(org_id, "plan_started", sub)
            elif after.id == self._catalog.free.id:
                await self._queue_owner_email(org_id, "plan_ended", sub, ended_plan=before)
        elif sub.is_paid and was_cancelling != sub.cancel_at_period_end:
            await self._audit.record(
                AuditAction.BILLING_RENEWAL_CHANGED,
                organization_id=org_id,
                details={
                    SYSTEM_FLAG: True,
                    "renews": not sub.cancel_at_period_end,
                    "until": sub.current_period_end.isoformat() if sub.current_period_end else None,
                },
            )
        return "applied"

    # --- emails (sent after the commit) ---------------------------------------------------

    async def _queue_owner_email(
        self,
        organization_id: uuid.UUID,
        kind: Literal["plan_started", "plan_ended", "payment_failed", "trial_ending"],
        sub: Subscription,
        *,
        ended_plan: PlanDefinition | None = None,
    ) -> None:
        owner = await self._repo.owner(organization_id)
        org = await OrganizationRepository(self._db).get(organization_id)
        if owner is None or org is None:
            return
        plan = self._effective(sub)
        common: dict[str, Any] = {
            "to": owner.email,
            "name": owner.name,
            "organization_name": org.name,
            "billing_url": self._billing_url,
            "app_name": self._settings.app_name,
        }
        message: EmailMessage
        if kind == "plan_started":
            trial = _date(sub.trial_end) if sub.status == "trialing" else None
            message = emails.plan_started_email(**common, plan_name=plan.name, trial_end=trial)
        elif kind == "plan_ended":
            message = emails.plan_ended_email(
                **common,
                plan_name=(ended_plan or plan).name,
                free_plan_name=self._catalog.free.name,
            )
        elif kind == "payment_failed":
            message = emails.payment_failed_email(**common, plan_name=plan.name)
        else:
            message = emails.trial_ending_email(
                **common, plan_name=plan.name, trial_end=_date(sub.trial_end)
            )
        self._pending.append(message)

    async def _send_pending(self) -> None:
        pending, self._pending = self._pending, []
        for message in pending:
            await self._email.send(message)

    # --- local development only (BILLING_DEV_TOOLS) ---------------------------------------

    async def dev_apply(
        self,
        organization_id: uuid.UUID,
        customer_id: str,
        *,
        plan_id: str | None,
        status: str,
        interval: str | None = "month",
        trial_days: int = 0,
        cancel_at_period_end: bool = False,
    ) -> None:
        """Pretend Stripe changed the subscription (same code path as a webhook)."""
        now = datetime.now(UTC)
        sub = await self._repo.get_or_create_subscription(organization_id)
        if sub.stripe_customer_id is None:
            sub.stripe_customer_id = customer_id
        elif sub.stripe_customer_id != customer_id:
            raise ConflictError("This link belongs to another billing account.")
        await self._db.flush()
        period = timedelta(days=365 if interval == "year" else 30)
        trial_end = now + timedelta(days=trial_days) if trial_days else None
        await self.apply_snapshot(
            SubscriptionSnapshot(
                id=sub.stripe_subscription_id or f"sub_dev_{uuid.uuid4().hex[:20]}",
                customer_id=customer_id,
                status=status,
                plan_id=plan_id,
                interval=interval,
                current_period_end=trial_end or (sub.current_period_end or now + period),
                cancel_at_period_end=cancel_at_period_end,
                trial_end=trial_end or (sub.trial_end if status == "trialing" else None),
            )
        )
        await self._db.commit()
        await self._send_pending()

    async def dev_state(self, customer_id: str) -> Subscription | None:
        """The billing row of a (dev) customer."""
        return await self._repo.find_by_customer(customer_id, lock=False)

    async def dev_payment_failed(self, organization_id: uuid.UUID, customer_id: str) -> None:
        """Pretend a renewal payment failed: past_due + the email to the owner."""
        sub = await self._repo.find_by_customer(customer_id)
        if sub is None or not sub.is_paid:
            return
        sub.status = "past_due"
        await self._queue_owner_email(organization_id, "payment_failed", sub)
        await self._db.commit()
        await self._send_pending()

    async def dev_set_plan(self, ctx: OrgContext, plan_id: str) -> None:
        """Put the workspace on a plan without paying (e2e tests, trying limits locally)."""
        ctx.require(Permission.BILLING_MANAGE)
        plan = self._catalog.get(plan_id)
        if plan is None:
            raise InvalidPlanError("There is no plan with this id.")
        sub = await self._repo.get_or_create_subscription(ctx.organization.id)
        customer = sub.stripe_customer_id or f"cus_dev_{uuid.uuid4().hex[:20]}"
        await self._db.commit()
        free = plan.id == self._catalog.free.id
        await self.dev_apply(
            ctx.organization.id,
            customer,
            plan_id=None if free else plan.id,
            status="canceled" if free else "active",
        )
