"""The real Stripe client code, with Stripe's HTTP answers faked (no network).

Checks what we SEND to Stripe (checkout parameters, idempotency key), how we READ Stripe's
objects (incl. the 2025+ API where the period lives on the subscription item), signature
checks with a real HMAC signature, and which gateway the settings pick.
"""

import hashlib
import hmac
import json
import time
import uuid
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
import stripe
from pydantic import SecretStr

from app.core.config import Environment, Settings
from app.core.plans import DEFAULT_CATALOG
from app.services.stripe_dev import DevGateway
from app.services.stripe_gateway import (
    InvalidWebhookError,
    PaymentProviderError,
    StripeGateway,
    WebhookEvent,
    gateway_for,
    snapshot_from_stripe,
)

WHSEC = "whsec_test_secret"


class FakeHttp(stripe.HTTPClient):
    """Answers Stripe API calls from a table and records them."""

    name = "fake"

    def __init__(self, routes: dict[tuple[str, str], tuple[int, dict[str, Any]]]) -> None:
        super().__init__()
        self.routes = routes
        self.calls: list[dict[str, Any]] = []

    def _answer(
        self, method: str, url: str, headers: Any, post_data: Any
    ) -> tuple[str, int, dict[str, str]]:
        parts = urlsplit(url)
        body = post_data.decode() if isinstance(post_data, bytes) else post_data or ""
        self.calls.append(
            {
                "method": method.upper(),
                "path": parts.path,
                "query": parse_qs(parts.query),
                "form": parse_qs(body),
                "headers": dict(headers),
            }
        )
        status, payload = self.routes.get((method.upper(), parts.path), (404, _missing()))
        return json.dumps(payload), status, {"request-id": "req_test"}

    def request(self, method: str, url: str, headers: Any, post_data: Any = None, **_: Any) -> Any:
        return self._answer(method, url, headers, post_data)

    async def request_async(
        self, method: str, url: str, headers: Any, post_data: Any = None, **_: Any
    ) -> Any:
        return self._answer(method, url, headers, post_data)

    def close(self) -> None:
        return None

    async def close_async(self) -> None:
        return None


def _missing() -> dict[str, Any]:
    return {
        "error": {
            "type": "invalid_request_error",
            "code": "resource_missing",
            "message": "No such object",
        }
    }


def _settings(**changes: Any) -> Settings:
    base: dict[str, Any] = {
        "_env_file": None,
        "environment": Environment.TEST,
        "stripe_secret_key": SecretStr("sk_test_123"),
        "stripe_webhook_secret": SecretStr(WHSEC),
    }
    return Settings(**{**base, **changes})


def _subscription(**extra: Any) -> dict[str, Any]:
    return {
        "id": "sub_1",
        "object": "subscription",
        "customer": "cus_1",
        "status": "trialing",
        "cancel_at_period_end": False,
        "trial_end": 1_900_000_000,
        "metadata": {"organization_id": "org-1", "app": "foundation"},
        "items": {
            "object": "list",
            "data": [
                {
                    "object": "subscription_item",
                    "current_period_end": 1_900_000_000,
                    "price": {
                        "object": "price",
                        "id": "price_1",
                        "lookup_key": "foundation_pro_month",
                        "metadata": {"app": "foundation", "plan_id": "pro"},
                        "recurring": {"interval": "month"},
                    },
                }
            ],
        },
        **extra,
    }


def _routes(**overrides: tuple[int, dict[str, Any]]) -> dict[tuple[str, str], Any]:
    routes: dict[tuple[str, str], Any] = {
        ("POST", "/v1/customers"): (200, {"id": "cus_1", "object": "customer"}),
        ("GET", "/v1/prices"): (
            200,
            {
                "object": "list",
                "url": "/v1/prices",
                "has_more": False,
                "data": [
                    {"id": "price_1", "object": "price", "unit_amount": 2900, "currency": "eur"}
                ],
            },
        ),
        ("POST", "/v1/checkout/sessions"): (
            200,
            {"id": "cs_1", "object": "checkout.session", "url": "https://checkout.stripe.com/c/1"},
        ),
        ("GET", "/v1/billing_portal/configurations"): (
            200,
            {
                "object": "list",
                "url": "/v1/billing_portal/configurations",
                "has_more": False,
                "data": [
                    {"id": "bpc_other", "object": "billing_portal.configuration", "metadata": {}},
                    {
                        "id": "bpc_mine",
                        "object": "billing_portal.configuration",
                        "metadata": {"app": "foundation"},
                    },
                ],
            },
        ),
        ("POST", "/v1/billing_portal/sessions"): (
            200,
            {
                "id": "bps_1",
                "object": "billing_portal.session",
                "url": "https://billing.stripe.com/p/1",
            },
        ),
        ("GET", "/v1/subscriptions/sub_1"): (200, _subscription()),
        ("DELETE", "/v1/subscriptions/sub_1"): (200, _subscription(status="canceled")),
        ("DELETE", "/v1/customers/cus_1"): (
            200,
            {"id": "cus_1", "object": "customer", "deleted": True},
        ),
        ("POST", "/v1/checkout/sessions/cs_1/expire"): (
            200,
            {"id": "cs_1", "object": "checkout.session", "status": "expired"},
        ),
        ("POST", "/v1/checkout/sessions/cs_done/expire"): (
            400,
            {
                "error": {
                    "type": "invalid_request_error",
                    "message": "Only open sessions can be expired.",
                }
            },
        ),
        ("GET", "/v1/subscriptions"): (
            200,
            {
                "object": "list",
                "url": "/v1/subscriptions",
                "has_more": False,
                "data": [_subscription(), _subscription(id="sub_old", status="canceled")],
            },
        ),
    }
    for key, value in overrides.items():
        method, _, path = key.partition(" ")
        routes[(method, path)] = value
    return routes


def _gateway(http: FakeHttp, **changes: Any) -> StripeGateway:
    return StripeGateway(_settings(**changes), DEFAULT_CATALOG, http_client=http)


def _plan(plan_id: str) -> Any:
    plan = DEFAULT_CATALOG.get(plan_id)
    assert plan is not None
    return plan


# --- sending ------------------------------------------------------------------------------


async def test_checkout_sends_the_right_parameters() -> None:
    http = FakeHttp(_routes())
    gw = _gateway(http)
    org = uuid.uuid4()
    assert await gw.create_customer(organization_id=org, name="Acme", email="a@b.de") == "cus_1"
    customer_call = http.calls[-1]
    assert customer_call["headers"]["Idempotency-Key"] == f"foundation-customer-{org}"
    assert customer_call["form"]["metadata[organization_id]"] == [str(org)]

    session = await gw.create_checkout(
        customer_id="cus_1",
        organization_id=org,
        plan=_plan("pro"),
        interval="month",
        trial_days=14,
        success_url="https://app.test/settings/billing?checkout=success",
        cancel_url="https://app.test/settings/billing?checkout=cancelled",
    )
    assert (session.id, session.url) == ("cs_1", "https://checkout.stripe.com/c/1")
    price_call, checkout = http.calls[-2], http.calls[-1]
    assert price_call["query"]["lookup_keys[0]"] == ["foundation_pro_month"]
    form = checkout["form"]
    assert form["mode"] == ["subscription"] and form["customer"] == ["cus_1"]
    assert form["line_items[0][price]"] == ["price_1"]
    assert form["client_reference_id"] == [str(org)]
    assert form["subscription_data[trial_period_days]"] == ["14"]
    assert form["subscription_data[trial_settings][end_behavior][missing_payment_method]"] == [
        "cancel"
    ]
    assert form["subscription_data[metadata][organization_id]"] == [str(org)]
    assert form["tax_id_collection[enabled]"] == ["true"]
    assert form["billing_address_collection"] == ["required"]
    assert form["automatic_tax[enabled]"] == ["false"]


async def test_no_trial_means_no_trial_parameters() -> None:
    http = FakeHttp(_routes())
    await _gateway(http, stripe_automatic_tax=True).create_checkout(
        customer_id="cus_1",
        organization_id=uuid.uuid4(),
        plan=_plan("pro"),
        interval="month",
        trial_days=0,
        success_url="https://x/s",
        cancel_url="https://x/c",
    )
    form = http.calls[-1]["form"]
    assert not any(k.startswith("subscription_data[trial") for k in form)
    assert form["automatic_tax[enabled]"] == ["true"]


async def test_checkout_refuses_a_price_that_differs_from_plans_py() -> None:
    wrong = {
        "object": "list",
        "url": "/v1/prices",
        "has_more": False,
        "data": [{"id": "price_1", "object": "price", "unit_amount": 1900, "currency": "eur"}],
    }
    for routes in (
        _routes(**{"GET /v1/prices": (200, wrong)}),
        _routes(**{"GET /v1/prices": (200, {**wrong, "data": []})}),
    ):
        http = FakeHttp(routes)
        with pytest.raises(PaymentProviderError):
            await _gateway(http).create_checkout(
                customer_id="cus_1",
                organization_id=uuid.uuid4(),
                plan=_plan("pro"),
                interval="month",
                trial_days=0,
                success_url="https://x/s",
                cancel_url="https://x/c",
            )
        assert not any(c["path"] == "/v1/checkout/sessions" for c in http.calls)


async def test_stripe_errors_become_a_calm_503() -> None:
    http = FakeHttp(
        _routes(
            **{
                "POST /v1/customers": (
                    400,
                    {
                        "error": {
                            "type": "invalid_request_error",
                            "message": "Bad email sk_test_123",
                        }
                    },
                )
            }
        )
    )
    with pytest.raises(PaymentProviderError) as info:
        await _gateway(http).create_customer(organization_id=uuid.uuid4(), name="A", email="x")
    assert "sk_test" not in info.value.message


async def test_portal_uses_this_products_configuration_once() -> None:
    http = FakeHttp(_routes())
    gw = _gateway(http)
    for _ in range(2):
        url = await gw.create_portal(customer_id="cus_1", return_url="https://app/billing")
        assert url == "https://billing.stripe.com/p/1"
    sessions = [c for c in http.calls if c["path"] == "/v1/billing_portal/sessions"]
    assert all(s["form"]["configuration"] == ["bpc_mine"] for s in sessions)
    lookups = [c for c in http.calls if c["path"] == "/v1/billing_portal/configurations"]
    assert len(lookups) == 1  # cached


async def test_reading_and_cancelling_subscriptions() -> None:
    http = FakeHttp(_routes())
    gw = _gateway(http)
    snap = await gw.get_subscription("sub_1")
    assert snap is not None
    assert (snap.plan_id, snap.interval, snap.status) == ("pro", "month", "trialing")
    assert snap.current_period_end is not None and snap.current_period_end.year == 2030
    assert snap.organization_id == "org-1"
    assert await gw.get_subscription("sub_gone") is None
    gw.delete_customer("cus_1")
    assert (http.calls[-1]["method"], http.calls[-1]["path"]) == ("DELETE", "/v1/customers/cus_1")
    gw.delete_customer("cus_gone")  # already gone: fine
    await gw.cancel_subscription("sub_1")
    assert (http.calls[-1]["method"], http.calls[-1]["path"]) == (
        "DELETE",
        "/v1/subscriptions/sub_1",
    )
    await gw.cancel_subscription("sub_gone")
    await gw.expire_checkout("cs_1")
    assert http.calls[-1]["path"] == "/v1/checkout/sessions/cs_1/expire"
    await gw.expire_checkout("cs_done")  # Stripe refuses finished sessions: fine
    live = await gw.live_subscriptions("cus_1")
    assert [x.id for x in live] == ["sub_1"]  # the canceled one is left out
    assert http.calls[-1]["query"]["status"] == ["all"]


# --- reading Stripe objects ---------------------------------------------------------------


def test_snapshot_reads_old_and_new_api_shapes() -> None:
    old = _subscription(current_period_end=1_800_000_000)
    old["items"]["data"][0].pop("current_period_end")
    assert snapshot_from_stripe(old, "foundation").current_period_end is not None
    # Another product in the same Stripe account: not one of our plans.
    other = _subscription()
    other["items"]["data"][0]["price"]["metadata"] = {"app": "askdocs", "plan_id": "pro"}
    other["items"]["data"][0]["price"]["lookup_key"] = "askdocs_pro_month"
    assert snapshot_from_stripe(other, "foundation").plan_id is None
    # No metadata: the lookup key is enough.
    bare = _subscription()
    bare["items"]["data"][0]["price"]["metadata"] = {}
    assert snapshot_from_stripe(bare, "foundation").plan_id == "pro"
    # cancel_at (portal "cancel at a date") also means "ends".
    assert snapshot_from_stripe(
        _subscription(cancel_at=1_900_000_000), "foundation"
    ).cancel_at_period_end
    empty = snapshot_from_stripe(
        {"id": "sub_9", "customer": {"id": "cus_9"}, "status": "active"}, "x"
    )
    assert (empty.customer_id, empty.plan_id, empty.current_period_end) == ("cus_9", None, None)


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({"object": "subscription", "id": "sub_1"}, "sub_1"),
        ({"object": "checkout.session", "subscription": "sub_2"}, "sub_2"),
        ({"object": "invoice", "subscription": {"id": "sub_3"}}, "sub_3"),
        (
            {"object": "invoice", "parent": {"subscription_details": {"subscription": "sub_4"}}},
            "sub_4",
        ),
        ({"object": "invoice", "parent": None}, None),
        ({"object": "checkout.session", "mode": "payment"}, None),
    ],
)
def test_which_subscription_an_event_is_about(data: dict[str, Any], expected: str | None) -> None:
    assert WebhookEvent(id="evt", type="x", data=data).subscription_id == expected


# --- webhook signatures -------------------------------------------------------------------


def _sign(payload: bytes, secret: str = WHSEC, at: int | None = None) -> str:
    ts = at or int(time.time())
    mac = hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={ts},v1={mac}"


def test_webhook_signature_is_checked_with_stripe_code() -> None:
    gw = _gateway(FakeHttp({}))
    payload = json.dumps(
        {
            "id": "evt_1",
            "object": "event",
            "type": "customer.subscription.updated",
            "data": {"object": _subscription()},
        }
    ).encode()
    event = gw.parse_event(payload, _sign(payload))
    assert (event.id, event.type, event.subscription_id) == (
        "evt_1",
        "customer.subscription.updated",
        "sub_1",
    )
    assert event.customer_id == "cus_1"
    for bad in (
        _sign(payload, secret="whsec_wrong"),
        _sign(payload, at=int(time.time()) - 3600),  # replayed an hour later
        _sign(payload + b" "),  # body changed
        "",
        None,
    ):
        with pytest.raises(InvalidWebhookError):
            gw.parse_event(payload, bad)
    no_secret = _gateway(FakeHttp({}), stripe_webhook_secret=None)
    with pytest.raises(InvalidWebhookError):
        no_secret.parse_event(payload, _sign(payload))


# --- choosing the gateway -----------------------------------------------------------------


def test_settings_pick_the_gateway() -> None:
    off = Settings(_env_file=None, environment=Environment.TEST)
    assert gateway_for(off, DEFAULT_CATALOG) is None
    dev = gateway_for(off.model_copy(update={"billing_dev_tools": True}), DEFAULT_CATALOG)
    assert isinstance(dev, DevGateway)
    live = _settings()
    first = gateway_for(live, DEFAULT_CATALOG)
    assert isinstance(first, StripeGateway)
    assert gateway_for(live, DEFAULT_CATALOG) is first  # one per process (connection pool)
    # Real keys win over dev tools.
    both = gateway_for(live.model_copy(update={"billing_dev_tools": True}), DEFAULT_CATALOG)
    assert isinstance(both, StripeGateway)


async def test_dev_gateway_links_are_relative_and_signed() -> None:
    settings = Settings(_env_file=None, environment=Environment.TEST, billing_dev_tools=True)
    dev = DevGateway(settings)
    session = await dev.create_checkout(
        customer_id="cus_dev_1",
        organization_id=uuid.uuid4(),
        plan=_plan("pro"),
        interval="year",
        trial_days=14,
        success_url=f"{settings.app_url}/settings/billing?checkout=success",
        cancel_url=f"{settings.app_url}/settings/billing?checkout=cancelled",
    )
    assert session.url.startswith("/api/billing/dev/checkout?token=")
    assert session.id.startswith("cs_dev_")
    from app.core.security import unsign_data

    data = unsign_data(session.url.split("token=")[1], settings.secret_key.get_secret_value())
    assert data is not None and data["success_url"] == "/settings/billing?checkout=success"
    portal = await dev.create_portal(customer_id="cus_dev_1", return_url="https://elsewhere/x")
    assert portal.startswith("/api/billing/dev/portal?token=")
    assert await dev.get_subscription("sub") is None
    assert await dev.live_subscriptions("cus") == []
    await dev.cancel_subscription("sub")
    await dev.expire_checkout("cs")
    dev.delete_customer("cus")
    with pytest.raises(InvalidWebhookError):
        dev.parse_event(b"{}", "sig")
