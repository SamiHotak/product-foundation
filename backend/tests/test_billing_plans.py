"""Public plan list for the pricing page (GET /api/billing/plans)."""

from httpx import AsyncClient

from app.core import plans as plan_config
from app.core.plans import PlanDefinition, PlanLimits, get_plan
from app.services.billing import public_plans


async def test_plans_are_public_and_match_the_config(client: AsyncClient) -> None:
    response = await client.get("/api/billing/plans")  # no sign-in

    assert response.status_code == 200
    assert "max-age=300" in response.headers["cache-control"]
    body = response.json()
    assert body["currency"] == plan_config.CURRENCY
    assert body["prices_include_vat"] is plan_config.PRICES_INCLUDE_VAT
    assert [p["id"] for p in body["plans"]] == [p.id for p in plan_config.PLANS if p.public]
    pro = next(p for p in body["plans"] if p["id"] == "pro")
    assert pro["price_monthly"] == 2900
    assert pro["limits"] == {"members": 5, "jobs_per_month": 2000, "api_keys": 10}
    assert pro["highlighted"] is True


def test_config_is_sane() -> None:
    ids = [p.id for p in plan_config.PLANS]
    assert len(ids) == len(set(ids)), "plan ids must be unique"
    assert sum(p.highlighted for p in plan_config.PLANS if p.public) <= 1
    for plan in plan_config.PLANS:
        assert plan.price_monthly >= 0 and plan.price_yearly >= 0
        assert plan.features, f"{plan.id} needs at least one feature line"
    assert get_plan("pro") is not None
    assert get_plan("nope") is None


def test_hidden_plans_are_not_listed() -> None:
    legacy = PlanDefinition(
        id="legacy",
        name="Legacy",
        description="Old plan.",
        price_monthly=500,
        price_yearly=5000,
        limits=PlanLimits(members=None, jobs_per_month=None, api_keys=None),
        features=("Everything",),
        public=False,
    )
    visible = PlanDefinition(
        id="team",
        name="Team",
        description="Now.",
        price_monthly=1000,
        price_yearly=10000,
        limits=PlanLimits(members=3, jobs_per_month=None, api_keys=2),
        features=("Three people",),
        contact_sales=True,
    )
    plans = public_plans((legacy, visible), currency="usd", prices_include_vat=True)

    assert [p.id for p in plans.plans] == ["team"]
    assert plans.currency == "usd"
    assert plans.prices_include_vat is True
    assert plans.plans[0].contact_sales is True
    assert plans.plans[0].limits.jobs_per_month is None
