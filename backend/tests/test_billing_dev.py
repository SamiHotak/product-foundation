"""The pretend checkout and portal (BILLING_DEV_TOOLS) and the rules around them."""

import re
import uuid
from typing import Any

import pytest
from pydantic import SecretStr

from app.core.config import Environment, Settings, get_settings
from app.core.plans import DEFAULT_CATALOG
from app.core.security import sign_data, unsign_data
from app.routers.deps import get_payment_gateway
from app.services.jobs import JobService
from app.services.stripe_dev import DevGateway
from tests.fakes import FakeDispatcher, FakeJobStore
from tests.helpers import World, build_world


def _dev_world() -> World:
    world = build_world(DEFAULT_CATALOG, billing_dev_tools=True)  # mounts the dev pages
    dev = DevGateway(get_settings().model_copy(update={"billing_dev_tools": True}))
    world.app.dependency_overrides[get_payment_gateway] = lambda: dev
    return world


def _form(html: str, action: str) -> dict[str, str]:
    token = re.search(r"name='token' value='([^']+)'", html)
    assert token, "no form on the page"
    return {"token": token.group(1), "action": action}


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_pretend_checkout_and_portal_use_the_real_billing_code() -> None:
    world = _dev_world()
    async with world.client() as c:
        await world.signup_and_verify(c, "owner@example.com", "Olga")
        assert (await c.get("/api/billing/current")).json()["provider"] == "dev"
        url = (await c.post("/api/billing/checkout", json={"plan_id": "pro"})).json()["url"]
        assert url.startswith("/api/billing/dev/checkout?token=")

        page = await c.get(url)
        assert page.status_code == 200 and "Pay (pretend)" in page.text
        assert "TEST MODE" in page.text and "Free for 14 days" in page.text
        back = await c.post(url.split("?")[0], data=_form(page.text, "cancel"))
        assert back.status_code == 303 and back.headers["location"].endswith("checkout=cancelled")
        assert (await c.get("/api/billing/current")).json()["plan_id"] == "free"

        paid = await c.post(url.split("?")[0], data=_form(page.text, "pay"))
        assert paid.headers["location"] == "/settings/billing?checkout=success"
        body = (await c.get("/api/billing/current")).json()
        assert (body["plan_id"], body["status"]) == ("pro", "trialing")
        assert world.email.last_to("owner@example.com").subject == "Your Pro trial has started"

        portal_url = (await c.post("/api/billing/portal")).json()["url"]
        portal = await c.get(portal_url)
        assert "Plan: Pro (trialing, renews)" in portal.text
        action_url = portal_url.split("?")[0]
        await c.post(action_url, data=_form(portal.text, "cancel_at_period_end"))
        assert (await c.get("/api/billing/current")).json()["cancel_at_period_end"] is True
        await c.post(action_url, data=_form(portal.text, "payment_failed"))
        assert world.email.last_to("owner@example.com").subject.startswith("Payment failed")
        await c.post(action_url, data=_form(portal.text, "cancel_now"))
        assert (await c.get("/api/billing/current")).json()["plan_id"] == "free"
        assert "No paid plan" in (await c.get(portal_url)).text


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_set_plan_for_tests_and_bad_links() -> None:
    world = _dev_world()
    async with world.client() as c:
        await world.signup_and_verify(c, "owner@example.com")
        assert (
            await c.post("/api/billing/dev/set-plan", json={"plan_id": "business"})
        ).status_code == 204
        assert (await c.get("/api/billing/current")).json()["plan_id"] == "business"
        assert (
            await c.post("/api/billing/dev/set-plan", json={"plan_id": "free"})
        ).status_code == 204
        assert (await c.get("/api/billing/current")).json()["plan_id"] == "free"
        assert (await c.post("/api/billing/dev/set-plan", json={"plan_id": "x"})).status_code == 400

        res = await c.get("/api/billing/dev/checkout", params={"token": "forged.token"})
        assert res.status_code == 400 and res.json()["error"]["code"] == "invalid_link"


@pytest.mark.integration
@pytest.mark.usefixtures("clean_db")
async def test_dev_pages_do_not_exist_without_dev_tools() -> None:
    world = build_world()
    async with world.client() as c:
        await world.signup_and_verify(c, "owner@example.com")
        res = await c.post("/api/billing/dev/set-plan", json={"plan_id": "business"})
        assert res.status_code == 404


# --- units --------------------------------------------------------------------------------


def test_dev_tools_and_stripe_settings_are_checked() -> None:
    prod: dict[str, Any] = {
        "_env_file": None,
        "environment": Environment.PRODUCTION,
        "secret_key": SecretStr("a-very-long-random-production-secret"),
    }
    with pytest.raises(ValueError, match="BILLING_DEV_TOOLS"):
        Settings(**prod, billing_dev_tools=True)
    with pytest.raises(ValueError, match="STRIPE_WEBHOOK_SECRET"):
        Settings(**prod, stripe_secret_key=SecretStr("sk_live_x"))
    ok = Settings(
        **prod,
        stripe_secret_key=SecretStr("sk_live_x"),
        stripe_webhook_secret=SecretStr("whsec_x"),
    )
    assert ok.stripe_enabled
    dev_live: dict[str, Any] = {"_env_file": None, "environment": Environment.DEVELOPMENT}
    with pytest.raises(ValueError, match="LIVE Stripe key"):
        Settings(**dev_live, billing_dev_tools=True, stripe_secret_key=SecretStr("sk_live_x"))
    assert Settings(**dev_live, billing_dev_tools=True, stripe_secret_key=SecretStr("sk_test_x"))
    with pytest.raises(ValueError, match="STRIPE_PREFIX"):
        Settings(_env_file=None, environment=Environment.TEST, stripe_prefix="Bad-Prefix")
    assert not Settings(_env_file=None, environment=Environment.TEST).stripe_enabled


def test_signed_data_round_trip_and_tampering() -> None:
    token = sign_data({"a": "b", "n": 1}, "secret", max_age_seconds=60)
    data = unsign_data(token, "secret")
    assert data is not None and data["a"] == "b" and data["n"] == 1
    assert unsign_data(token, "other-secret") is None
    body, mac = token.rsplit(".", 1)
    assert unsign_data(body[:-1] + ("A" if body[-1] != "A" else "B") + "." + mac, "secret") is None
    assert unsign_data("nodot", "secret") is None and unsign_data(".x", "secret") is None
    expired = sign_data({"a": "b"}, "secret", max_age_seconds=-1)
    assert unsign_data(expired, "secret") is None


class FakeMeter:
    def __init__(self, fail: Exception | None = None) -> None:
        self.consumed: list[str] = []
        self.released: list[str] = []
        self.fail = fail

    async def consume(self, organization_id: uuid.UUID, metric: Any, amount: int = 1) -> None:
        if self.fail:
            raise self.fail
        self.consumed.append(metric)

    async def release(self, organization_id: uuid.UUID, metric: Any, amount: int = 1) -> None:
        self.released.append(metric)


async def test_jobs_are_metered_and_refunded_when_the_queue_is_down() -> None:
    from app.core.errors import ServiceUnavailableError
    from app.services.usage import LimitReachedError

    org = uuid.uuid4()
    meter = FakeMeter()
    service = JobService(FakeJobStore(), FakeDispatcher(), meter)
    await service.enqueue("example", {}, organization_id=org, created_by_id=None)
    await service.enqueue(
        "data_export", {"export_id": "x"}, organization_id=org, created_by_id=None
    )
    assert meter.consumed == ["jobs_per_month"]  # exports are never metered

    down = JobService(FakeJobStore(), FakeDispatcher(fail=True), meter)
    with pytest.raises(ServiceUnavailableError):
        await down.enqueue("example", {}, organization_id=org, created_by_id=None)
    assert meter.released == ["jobs_per_month"]

    store = FakeJobStore()
    full = JobService(store, FakeDispatcher(), FakeMeter(LimitReachedError("full")))
    with pytest.raises(LimitReachedError):
        await full.enqueue("example", {}, organization_id=org, created_by_id=None)
    assert store.jobs == {}  # nothing was created
