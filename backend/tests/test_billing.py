"""Billing: checkout, portal, Stripe webhooks (idempotent, order-independent), trial,
plan changes that apply at once, emails, workspace isolation, and the nightly purge.

Stripe itself is a fake (tests.fakes.FakeGateway). The real Stripe client code is tested
in test_stripe_gateway.py; a real test-mode run is documented in docs/BILLING.md.
"""

import asyncio
import json
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, update

from app.core.plans import DEFAULT_CATALOG
from app.db.session import sync_session
from app.models.billing import StripeEvent, Subscription
from app.models.organization import Organization
from app.routers.deps import get_payment_gateway
from app.services.purge import purge_due
from app.services.stripe_gateway import PaymentProviderError
from tests.helpers import World, build_world

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_db")]

CURRENT = "/api/billing/current"
CHECKOUT = "/api/billing/checkout"
PORTAL = "/api/billing/portal"
WEBHOOK = "/api/billing/webhook"


@pytest.fixture
def world() -> World:
    # The REAL plans (free: 1 person, 50 jobs, 1 API key), so limit changes are visible.
    return build_world(DEFAULT_CATALOG)


async def _webhook(
    c: AsyncClient,
    event_type: str,
    obj: dict[str, Any],
    *,
    event_id: str | None = None,
    signature: str = "valid",
) -> Any:
    body = {
        "id": event_id or f"evt_{uuid.uuid4().hex}",
        "type": event_type,
        "data": {"object": obj},
    }
    return await c.post(
        WEBHOOK,
        content=json.dumps(body),
        headers={"Stripe-Signature": signature, "Content-Type": "application/json"},
    )


async def _checkout(c: AsyncClient, plan: str = "pro", interval: str = "month") -> str:
    res = await c.post(CHECKOUT, json={"plan_id": plan, "interval": interval})
    assert res.status_code == 200, res.text
    url: str = res.json()["url"]
    return url


async def _pay(world: World, stripe_c: AsyncClient, customer_id: str, **sub: Any) -> None:
    """Stripe finished the checkout: it has the subscription and sends the webhook."""
    snap = world.stripe.set_subscription(customer_id, **sub)
    res = await _webhook(
        stripe_c,
        "checkout.session.completed",
        {"object": "checkout.session", "customer": customer_id, "subscription": snap.id},
    )
    assert res.status_code == 200, res.text


def _audit_actions(org_id: str) -> list[str]:
    from app.models.audit_log import AuditLog

    with sync_session() as s:
        rows = s.scalars(
            select(AuditLog.action)
            .where(AuditLog.organization_id == uuid.UUID(org_id))
            .order_by(AuditLog.created_at)
        )
        return list(rows)


# --- reading ----------------------------------------------------------------------------


async def test_new_workspace_is_on_free_with_usage(world: World) -> None:
    async with world.client() as c:
        await world.signup_and_verify(c, "owner@example.com", "Olga")
        body = (await c.get(CURRENT)).json()
        assert body["provider"] == "stripe"
        assert (body["plan_id"], body["plan_name"], body["status"]) == ("free", "Free", None)
        assert body["can_manage"] is True and body["trial_available"] is True
        assert body["has_billing_account"] is False
        usage = {u["metric"]: (u["used"], u["limit"]) for u in body["usage"]}
        assert usage == {
            "members": (1, 1),
            "jobs_per_month": (0, 50),
            "api_keys": (0, 1),
            "storage_mb": (0, 100),
            "ai_requests_per_month": (0, 50),
        }
        today = datetime.now(UTC).date()
        resets = date.fromisoformat(body["usage_resets_on"])
        assert resets.day == 1 and resets > today and (resets - today).days <= 31


async def test_payments_off_without_a_gateway(world: World) -> None:
    world.app.dependency_overrides[get_payment_gateway] = lambda: None
    async with world.client() as c:
        await world.signup_and_verify(c, "owner@example.com")
        assert (await c.get(CURRENT)).json()["provider"] == "none"
        res = await c.post(CHECKOUT, json={"plan_id": "pro"})
        assert res.status_code == 503
        assert res.json()["error"]["message"] == "Paid plans are not available yet."
        assert (await c.post(PORTAL)).status_code == 503


# --- checkout -----------------------------------------------------------------------------


async def test_checkout_creates_one_customer_and_offers_the_trial(world: World) -> None:
    async with world.client() as c:
        me = await world.signup_and_verify(c, "owner@example.com", "Olga")
        url = await _checkout(c, "pro", "month")
        assert url.startswith("https://checkout.stripe.test/")
        [customer] = world.stripe.customers
        assert customer["email"] == "owner@example.com"
        assert str(customer["organization_id"]) == me["active_organization_id"]
        call = world.stripe.checkouts[0]
        assert call["customer_id"] == customer["id"]
        assert call["plan"].id == "pro" and call["interval"] == "month"
        assert call["trial_days"] == 14
        assert call["success_url"].endswith("/settings/billing?checkout=success")
        assert call["cancel_url"].endswith("/settings/billing?checkout=cancelled")

        # Back without paying, then again (yearly): same customer, no duplicates.
        await _checkout(c, "business", "year")
        assert len(world.stripe.customers) == 1
        assert world.stripe.checkouts[1]["customer_id"] == customer["id"]
        assert (await c.get(CURRENT)).json()["has_billing_account"] is True
        assert _audit_actions(me["active_organization_id"]).count("billing.checkout_started") == 2


@pytest.mark.parametrize(
    ("body", "status", "code"),
    [
        ({"plan_id": "nope"}, 400, "invalid_plan"),
        ({"plan_id": "free"}, 400, "invalid_plan"),
        ({"plan_id": "pro", "interval": "week"}, 422, "validation_error"),
        ({"plan_id": ""}, 422, "validation_error"),
    ],
)
async def test_checkout_rejects_plans_that_cant_be_bought(
    world: World, body: dict[str, Any], status: int, code: str
) -> None:
    async with world.client() as c:
        await world.signup_and_verify(c, "owner@example.com")
        res = await c.post(CHECKOUT, json=body)
        assert res.status_code == status, res.text
        assert res.json()["error"]["code"] == code
        assert world.stripe.checkouts == []


async def test_only_the_owner_manages_billing(world: World) -> None:
    async with world.client() as owner, world.client() as admin:
        me = await world.signup_and_verify(owner, "owner@example.com")
        from tests.helpers import set_plan

        set_plan(me["active_organization_id"], "pro")  # room for a second person
        await world.invite_and_join(owner, admin, "admin@example.com", role="admin")
        assert (await admin.get(CURRENT)).json()["can_manage"] is False
        assert (await admin.get(CURRENT)).json()["plan_id"] == "pro"  # everyone sees the plan
        assert (await admin.post(CHECKOUT, json={"plan_id": "pro"})).status_code == 403
        assert (await admin.post(PORTAL)).status_code == 403
        assert (await owner.post(PORTAL)).status_code == 200


async def test_stripe_down_at_checkout_is_a_calm_503(world: World) -> None:
    world.stripe.fail = PaymentProviderError("Checkout is not available right now.")
    async with world.client() as c:
        await world.signup_and_verify(c, "owner@example.com")
        res = await c.post(CHECKOUT, json={"plan_id": "pro"})
        assert res.status_code == 503
        assert res.json()["error"]["code"] == "payment_provider_error"


# --- the whole life of a subscription -----------------------------------------------------


async def test_trial_upgrade_limits_cancel_and_back_to_free(world: World) -> None:
    async with world.client() as owner, world.client() as stripe_c:
        me = await world.signup_and_verify(owner, "owner@example.com", "Olga")
        org_id = me["active_organization_id"]
        keys = "/api/organizations/current/api-keys"
        assert (
            await owner.post(keys, json={"name": "a", "scopes": ["jobs:read"]})
        ).status_code == 201
        blocked = await owner.post(keys, json={"name": "b", "scopes": ["jobs:read"]})
        assert blocked.status_code == 402  # free: 1 key

        await _checkout(owner)
        customer = world.stripe.customers[0]["id"]
        await _pay(world, stripe_c, customer, status="trialing", trial_days=14)

        body = (await owner.get(CURRENT)).json()
        assert (body["plan_id"], body["status"], body["interval"]) == ("pro", "trialing", "month")
        assert body["trial_end"] is not None and body["trial_available"] is False
        # The new limits apply at once.
        assert (
            await owner.post(keys, json={"name": "b", "scopes": ["jobs:read"]})
        ).status_code == 201
        mail = world.email.last_to("owner@example.com")
        assert mail.subject == "Your Pro trial has started"
        assert "/settings/billing" in mail.text and mail.html and "Pro" in mail.html

        # Cancel in the portal: still Pro until the period ends.
        world.stripe.set_subscription(customer, status="active", cancel_at_period_end=True)
        await _webhook(
            stripe_c,
            "customer.subscription.updated",
            {"object": "subscription", "id": "sub_1", "customer": customer},
        )
        body = (await owner.get(CURRENT)).json()
        assert body["plan_id"] == "pro" and body["cancel_at_period_end"] is True

        # The period ends: Stripe deletes the subscription -> free, limits back.
        world.stripe.set_subscription(customer, status="canceled")
        await _webhook(
            stripe_c,
            "customer.subscription.deleted",
            {"object": "subscription", "id": "sub_1", "customer": customer},
        )
        body = (await owner.get(CURRENT)).json()
        assert (body["plan_id"], body["status"]) == ("free", "canceled")
        assert body["cancel_at_period_end"] is False and body["current_period_end"] is None
        assert world.email.last_to("owner@example.com").subject.endswith("is on the Free plan now")
        blocked = await owner.post(keys, json={"name": "c", "scopes": ["jobs:read"]})
        assert blocked.status_code == 402
        assert blocked.json()["error"]["details"]["used"] == 2  # nothing was deleted

        actions = _audit_actions(org_id)
        assert actions.count("billing.plan_changed") == 2
        assert "billing.renewal_changed" in actions

        # One trial per workspace: the next checkout has none.
        await _checkout(owner)
        assert world.stripe.checkouts[-1]["trial_days"] == 0


async def test_webhook_is_idempotent_even_in_parallel(world: World) -> None:
    async with world.client() as owner, world.client() as s1, world.client() as s2:
        await world.signup_and_verify(owner, "owner@example.com")
        await _checkout(owner)
        customer = world.stripe.customers[0]["id"]
        await _pay(world, stripe_c=s1, customer_id=customer)
        world.stripe.set_subscription(customer, status="past_due")
        # "Payment failed" sends an email every time it is handled, so a repeat would show.
        obj = {"object": "invoice", "customer": customer, "subscription": "sub_1"}
        sent_before = len(world.email.sent)
        first, second = await asyncio.gather(
            _webhook(s1, "invoice.payment_failed", obj, event_id="evt_same"),
            _webhook(s2, "invoice.payment_failed", obj, event_id="evt_same"),
        )
        assert (first.status_code, second.status_code) == (200, 200)
        again = await _webhook(s1, "invoice.payment_failed", obj, event_id="evt_same")
        assert again.status_code == 200
        assert len(world.email.sent) == sent_before + 1  # handled exactly once
        with sync_session() as s:
            ids = list(s.scalars(select(StripeEvent.id)))
            assert "evt_same" in ids and len(ids) == 2  # + the checkout event


async def test_webhook_signature_and_unknown_events(world: World) -> None:
    async with world.client() as c:
        res = await _webhook(
            c, "customer.subscription.updated", {"id": "sub_1"}, signature="forged"
        )
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "invalid_webhook"
        res = await c.post(WEBHOOK, content=b"{}")  # no signature header
        assert res.status_code == 400
        res = await _webhook(c, "charge.refunded", {"id": "ch_1"})  # not one we handle
        assert res.status_code == 200
        with sync_session() as s:
            assert s.scalar(select(func.count()).select_from(StripeEvent)) == 0


async def test_order_of_events_does_not_matter(world: World) -> None:
    """The event body may be old; we always read the subscription fresh from Stripe."""
    async with world.client() as owner, world.client() as stripe_c:
        await world.signup_and_verify(owner, "owner@example.com")
        await _checkout(owner)
        customer = world.stripe.customers[0]["id"]
        await _pay(world, stripe_c, customer)
        world.stripe.set_subscription(customer, status="canceled")
        # A late "updated" event that still says "active" in its body.
        stale = {"object": "subscription", "id": "sub_1", "status": "active", "customer": customer}
        await _webhook(stripe_c, "customer.subscription.updated", stale)
        assert (await owner.get(CURRENT)).json()["plan_id"] == "free"


async def test_an_old_subscription_never_replaces_the_current_one(world: World) -> None:
    async with world.client() as owner, world.client() as stripe_c:
        await world.signup_and_verify(owner, "owner@example.com")
        await _checkout(owner)
        customer = world.stripe.customers[0]["id"]
        await _pay(world, stripe_c, customer, sub_id="sub_new", plan_id="business")
        world.stripe.set_subscription(customer, sub_id="sub_old", status="canceled")
        await _webhook(
            stripe_c,
            "customer.subscription.deleted",
            {"object": "subscription", "id": "sub_old", "customer": customer},
        )
        assert (await owner.get(CURRENT)).json()["plan_id"] == "business"


async def test_events_of_other_products_are_ignored(world: World) -> None:
    """Several products can share one Stripe account; unknown customers are not ours."""
    async with world.client() as owner, world.client() as stripe_c:
        await world.signup_and_verify(owner, "owner@example.com")
        world.stripe.set_subscription("cus_other_product", sub_id="sub_x")
        res = await _webhook(
            stripe_c,
            "customer.subscription.created",
            {"object": "subscription", "id": "sub_x", "customer": "cus_other_product"},
        )
        assert res.status_code == 200
        assert (await owner.get(CURRENT)).json()["plan_id"] == "free"
        with sync_session() as s:
            assert s.scalar(select(func.count()).select_from(Subscription)) == 0


async def test_failed_payment_and_trial_ending_emails(world: World) -> None:
    async with world.client() as owner, world.client() as stripe_c:
        await world.signup_and_verify(owner, "owner@example.com", "Olga")
        await _checkout(owner)
        customer = world.stripe.customers[0]["id"]
        await _pay(world, stripe_c, customer, status="trialing", trial_days=3)

        await _webhook(
            stripe_c,
            "customer.subscription.trial_will_end",
            {"object": "subscription", "id": "sub_1", "customer": customer},
        )
        assert world.email.last_to("owner@example.com").subject.startswith("Your Pro trial ends on")

        world.stripe.set_subscription(customer, status="past_due")
        invoice = {
            "object": "invoice",
            "customer": customer,
            "parent": {"subscription_details": {"subscription": "sub_1"}},
        }
        await _webhook(stripe_c, "invoice.payment_failed", invoice)
        mail = world.email.last_to("owner@example.com")
        assert mail.subject.startswith("Payment failed for")
        assert "Update payment method" in (mail.html or "")
        body = (await owner.get(CURRENT)).json()
        assert (body["plan_id"], body["status"]) == ("pro", "past_due")  # grace while retrying

        world.stripe.set_subscription(customer, status="active")
        await _webhook(
            stripe_c,
            "invoice.paid",
            {"object": "invoice", "customer": customer, "subscription": "sub_1"},
        )
        assert (await owner.get(CURRENT)).json()["status"] == "active"


async def test_stripe_down_during_a_webhook_means_retry_later(world: World) -> None:
    async with world.client() as owner, world.client() as stripe_c:
        await world.signup_and_verify(owner, "owner@example.com")
        await _checkout(owner)
        customer = world.stripe.customers[0]["id"]
        world.stripe.set_subscription(customer)
        obj = {"object": "checkout.session", "customer": customer, "subscription": "sub_1"}
        world.stripe.fail = PaymentProviderError("down")
        res = await _webhook(stripe_c, "checkout.session.completed", obj, event_id="evt_retry")
        assert res.status_code == 503  # Stripe will send it again
        with sync_session() as s:
            assert s.scalar(select(func.count()).select_from(StripeEvent)) == 0
        world.stripe.fail = None
        res = await _webhook(stripe_c, "checkout.session.completed", obj, event_id="evt_retry")
        assert res.status_code == 200
        assert (await owner.get(CURRENT)).json()["plan_id"] == "pro"


async def test_already_paying_workspaces_use_the_portal(world: World) -> None:
    async with world.client() as owner, world.client() as stripe_c:
        await world.signup_and_verify(owner, "owner@example.com")
        assert (await owner.post(PORTAL)).status_code == 404  # no billing account yet
        await _checkout(owner)
        await _pay(world, stripe_c, world.stripe.customers[0]["id"])
        res = await owner.post(CHECKOUT, json={"plan_id": "business"})
        assert res.status_code == 409
        assert "Manage billing" in res.json()["error"]["message"]
        res = await owner.post(PORTAL)
        assert res.status_code == 200 and res.json()["url"].startswith(
            "https://billing.stripe.test"
        )
        assert world.stripe.portals[-1]["return_url"].endswith("/settings/billing")


async def test_one_workspace_never_touches_another(world: World) -> None:
    async with world.client() as a, world.client() as b, world.client() as stripe_c:
        await world.signup_and_verify(a, "a@example.com")
        await world.signup_and_verify(b, "b@example.com")
        await _checkout(a)
        await _checkout(b)
        cus_a, cus_b = (c["id"] for c in world.stripe.customers)
        assert cus_a != cus_b
        await _pay(world, stripe_c, cus_a, sub_id="sub_a", plan_id="business")
        assert (await a.get(CURRENT)).json()["plan_id"] == "business"
        assert (await b.get(CURRENT)).json()["plan_id"] == "free"
        # B's portal opens B's customer, never A's.
        await b.post(PORTAL)
        assert world.stripe.portals[-1]["customer_id"] == cus_b


# --- nightly purge ------------------------------------------------------------------------


async def test_deleting_a_workspace_deletes_its_stripe_customer(world: World) -> None:
    async with world.client() as owner:
        me = await world.signup_and_verify(owner, "owner@example.com")
        org_id = uuid.UUID(me["active_organization_id"])
        from tests.helpers import set_plan

        set_plan(str(org_id), "pro", customer_id="cus_paid")
        await owner.post("/api/organizations", json={"name": "Second"})  # keep the account
        with sync_session() as s:
            s.execute(
                update(Organization)
                .where(Organization.id == org_id)
                .values(deletion_scheduled_at=datetime.now(UTC) - timedelta(minutes=1))
            )

    # Stripe down: the workspace is NOT deleted (we must not delete and keep charging).
    world.stripe.delete_error = ConnectionError("stripe down")
    purge = world.stripe.delete_customer
    assert purge_due(sync_session, datetime.now(UTC), purge)["workspaces"] == 0
    with sync_session() as s:
        assert s.get(Organization, org_id) is not None

    world.stripe.delete_error = None
    assert purge_due(sync_session, datetime.now(UTC), purge)["workspaces"] == 1
    # Deleting the customer ends EVERY subscription and removes the personal data at Stripe.
    assert world.stripe.deleted_customers == ["cus_paid"]
    with sync_session() as s:
        assert s.get(Organization, org_id) is None
        assert s.scalar(select(func.count()).select_from(Subscription)) == 0


# --- review fixes: races and double subscriptions -----------------------------------------


async def test_webhook_locks_the_workspace_before_asking_stripe(world: World) -> None:
    """A slow event must not overwrite a newer one: the row is locked while Stripe is read."""
    import psycopg
    from sqlalchemy import text
    from sqlalchemy.exc import OperationalError

    async with world.client() as owner, world.client() as stripe_c:
        await world.signup_and_verify(owner, "owner@example.com")
        await _checkout(owner)
        customer = world.stripe.customers[0]["id"]
        world.stripe.set_subscription(customer)
        seen: list[str] = []

        def check_locked(_sub_id: str) -> None:
            with sync_session() as s:
                s.execute(text("SET LOCAL lock_timeout = '200ms'"))
                try:
                    s.execute(
                        select(Subscription.id)
                        .where(Subscription.stripe_customer_id == customer)
                        .with_for_update(nowait=True)
                    )
                    seen.append("free")
                except OperationalError as exc:
                    assert isinstance(exc.orig, psycopg.errors.LockNotAvailable)
                    seen.append("locked")
                    s.rollback()

        world.stripe.on_get = check_locked
        obj = {"object": "subscription", "id": "sub_1", "customer": customer}
        assert (await _webhook(stripe_c, "customer.subscription.updated", obj)).status_code == 200
        assert seen == ["locked"]


async def test_a_second_checkout_closes_the_first(world: World) -> None:
    """Two browser tabs can't create two subscriptions (or a second trial)."""
    async with world.client() as owner:
        await world.signup_and_verify(owner, "owner@example.com")
        await _checkout(owner, "pro")
        assert world.stripe.expired == []
        await _checkout(owner, "business")
        assert world.stripe.expired == ["cs_test_1"]
        await _checkout(owner, "pro")
        assert world.stripe.expired == ["cs_test_1", "cs_test_2"]


async def test_checkout_settles_what_stripe_still_has(world: World) -> None:
    async with world.client() as owner, world.client() as stripe_c:
        await world.signup_and_verify(owner, "owner@example.com")
        await _checkout(owner)
        customer = world.stripe.customers[0]["id"]
        # An unpaid leftover (gives no plan) is ended before the new checkout.
        world.stripe.set_subscription(customer, sub_id="sub_unpaid", status="unpaid")
        await _checkout(owner, "business")
        assert world.stripe.cancelled == ["sub_unpaid"]

        # Our copy missed a webhook, but Stripe says the workspace already pays: refuse, fix.
        world.stripe.set_subscription(customer, sub_id="sub_paid", status="active")
        res = await owner.post(CHECKOUT, json={"plan_id": "pro"})
        assert res.status_code == 409
        assert (await owner.get(CURRENT)).json()["plan_id"] == "pro"
        assert len(world.stripe.checkouts) == 2  # no third checkout was created
        assert (
            await stripe_c.get(CURRENT)
        ).status_code == 401  # (the stripe client has no session)


async def test_a_second_paying_subscription_never_replaces_the_first(world: World) -> None:
    async with world.client() as owner, world.client() as stripe_c:
        me = await world.signup_and_verify(owner, "owner@example.com")
        await _checkout(owner)
        customer = world.stripe.customers[0]["id"]
        await _pay(world, stripe_c, customer, sub_id="sub_a", plan_id="pro")
        # Somehow a second one also got paid (e.g. an old open checkout). Keep the first.
        world.stripe.set_subscription(customer, sub_id="sub_b", plan_id="business")
        res = await _webhook(
            stripe_c,
            "customer.subscription.created",
            {"object": "subscription", "id": "sub_b", "customer": customer},
        )
        assert res.status_code == 200
        assert (await owner.get(CURRENT)).json()["plan_id"] == "pro"
        with sync_session() as s:
            row = s.scalar(
                select(Subscription).where(
                    Subscription.organization_id == uuid.UUID(me["active_organization_id"])
                )
            )
            assert row is not None and row.stripe_subscription_id == "sub_a"

        # But when the first one really ended, the new one takes over.
        world.stripe.set_subscription(customer, sub_id="sub_a", status="canceled")
        await _webhook(
            stripe_c,
            "customer.subscription.updated",
            {"object": "subscription", "id": "sub_b", "customer": customer},
        )
        assert (await owner.get(CURRENT)).json()["plan_id"] == "business"


async def test_old_subscriptions_never_overwrite_or_send_emails(world: World) -> None:
    async with world.client() as owner, world.client() as stripe_c:
        await world.signup_and_verify(owner, "owner@example.com")
        await _checkout(owner)
        customer = world.stripe.customers[0]["id"]
        await _pay(world, stripe_c, customer, sub_id="sub_now")
        # An unpaid, different subscription can't replace a paid plan.
        world.stripe.set_subscription(customer, sub_id="sub_x", status="incomplete")
        await _webhook(
            stripe_c,
            "customer.subscription.created",
            {"object": "subscription", "id": "sub_x", "customer": customer},
        )
        assert (await owner.get(CURRENT)).json()["plan_id"] == "pro"
        # A failed payment of an OLD, ended subscription: no "payment failed" email.
        world.stripe.set_subscription(customer, sub_id="sub_old", status="canceled")
        sent = len(world.email.sent)
        invoice = {"object": "invoice", "customer": customer, "subscription": "sub_old"}
        await _webhook(stripe_c, "invoice.payment_failed", invoice)
        assert len(world.email.sent) == sent

        # When the current one is unpaid, an old cancelled one still can't overwrite it
        # (the nightly purge must find the live subscription's customer).
        world.stripe.set_subscription(customer, sub_id="sub_now", status="unpaid")
        await _webhook(
            stripe_c,
            "customer.subscription.updated",
            {"object": "subscription", "id": "sub_now", "customer": customer},
        )
        await _webhook(
            stripe_c,
            "customer.subscription.deleted",
            {"object": "subscription", "id": "sub_old", "customer": customer},
        )
        body = (await owner.get(CURRENT)).json()
        assert (body["plan_id"], body["status"]) == ("free", "unpaid")
