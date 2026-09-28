"""Plan limits with the REAL plans: free = 1 person, 50 jobs a month, 1 API key.

Jobs are metered per calendar month; seats and API keys are counted. Parallel requests
can't go past a limit. Upgrading lifts a limit at once; downgrading deletes nothing.
"""

import asyncio
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from app.core.plans import DEFAULT_CATALOG
from app.db.session import sync_session
from app.models.api_key import ApiKey
from app.models.billing import UsageRecord
from app.services.usage import month_start, next_month_start
from tests.helpers import World, build_world, set_plan

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_db")]

INVITES = "/api/organizations/current/invites"
KEYS = "/api/organizations/current/api-keys"


@pytest.fixture
def world() -> World:
    return build_world(DEFAULT_CATALOG)


def _set_usage(org_id: str, count: int, month: date | None = None) -> None:
    values = {
        "organization_id": uuid.UUID(org_id),
        "metric": "jobs_per_month",
        "period_start": month or month_start(datetime.now(UTC)),
        "count": count,
    }
    with sync_session() as s:
        s.execute(
            insert(UsageRecord)
            .values(**values)
            .on_conflict_do_update(
                index_elements=["organization_id", "metric", "period_start"],
                set_={"count": count},
            )
        )


def _usage(org_id: str) -> int:
    with sync_session() as s:
        value = s.scalar(
            select(UsageRecord.count).where(
                UsageRecord.organization_id == uuid.UUID(org_id),
                UsageRecord.period_start == month_start(datetime.now(UTC)),
            )
        )
        return int(value or 0)


async def _job(c: AsyncClient, **headers: str) -> Any:
    return await c.post("/api/jobs/example", json={"steps": 1}, headers=headers)


# --- metered: jobs per month -------------------------------------------------------------


async def test_jobs_stop_at_the_monthly_limit_and_upgrading_lifts_it(world: World) -> None:
    async with world.client() as c:
        me = await world.signup_and_verify(c, "owner@example.com")
        org = me["active_organization_id"]
        _set_usage(org, 49)
        assert (await _job(c)).status_code == 202
        res = await _job(c)
        assert res.status_code == 402
        err = res.json()["error"]
        assert err["code"] == "limit_reached"
        assert err["details"] == {
            "metric": "jobs_per_month",
            "limit": 50,
            "used": 50,
            "plan_id": "free",
            "plan_name": "Free",
        }
        assert "all 50 background jobs of the Free plan" in err["message"]
        assert len(world.dispatched) == 1 and _usage(org) == 50  # the refused one never ran

        set_plan(org, "pro")  # a webhook did this in real life
        assert (await _job(c)).status_code == 202
        assert _usage(org) == 51


async def test_parallel_requests_cannot_pass_the_limit(world: World) -> None:
    async with world.client() as c:
        me = await world.signup_and_verify(c, "owner@example.com")
        org = me["active_organization_id"]
        _set_usage(org, 45)
        results = await asyncio.gather(*(_job(c) for _ in range(12)))
        codes = sorted(r.status_code for r in results)
        assert codes == [202] * 5 + [402] * 7
        assert _usage(org) == 50


async def test_last_month_does_not_count(world: World) -> None:
    async with world.client() as c:
        me = await world.signup_and_verify(c, "owner@example.com")
        org = me["active_organization_id"]
        last_month = month_start(datetime.now(UTC).replace(day=1) - timedelta(days=1))
        _set_usage(org, 50, last_month)
        assert (await _job(c)).status_code == 202
        usage = {
            u["metric"]: u["used"] for u in (await c.get("/api/billing/current")).json()["usage"]
        }
        assert usage["jobs_per_month"] == 1


async def test_api_keys_are_limited_like_people(world: World) -> None:
    """A script with an API key hits the same monthly limit."""
    async with world.client() as c, world.client() as script:
        me = await world.signup_and_verify(c, "owner@example.com")
        key = (await c.post(KEYS, json={"name": "ci", "scopes": ["jobs:write"]})).json()["key"]
        _set_usage(me["active_organization_id"], 50)
        res = await _job(script, Authorization=f"Bearer {key}")
        assert res.status_code == 402 and res.json()["error"]["code"] == "limit_reached"


async def test_gdpr_exports_never_count(world: World) -> None:
    async with world.client() as c:
        me = await world.signup_and_verify(c, "owner@example.com")
        _set_usage(me["active_organization_id"], 50)
        assert (await c.post("/api/account/exports")).status_code == 202
        assert (await c.post("/api/organizations/current/exports")).status_code == 202
        assert _usage(me["active_organization_id"]) == 50


# --- seats --------------------------------------------------------------------------------


async def test_seats_count_members_and_open_invites(world: World) -> None:
    async with world.client() as owner, world.client() as joiner, world.client() as late:
        me = await world.signup_and_verify(owner, "owner@example.com")
        org = me["active_organization_id"]
        res = await owner.post(INVITES, json={"email": "a@example.com", "role": "member"})
        assert res.status_code == 402  # free: only the owner
        assert res.json()["error"]["details"]["metric"] == "members"
        assert "allows 1 person" in res.json()["error"]["message"]
        assert world.email.sent[-1].to == "owner@example.com"  # no invite email went out

        set_plan(org, "pro")  # 5 people
        await world.invite_and_join(owner, joiner, "a@example.com")  # 2 members
        for i in range(3):  # + 3 open invites = 5
            ok = await owner.post(INVITES, json={"email": f"p{i}@example.com", "role": "member"})
            assert ok.status_code == 201, ok.text
        full = await owner.post(INVITES, json={"email": "x@example.com", "role": "member"})
        assert full.status_code == 402
        # Sending again to the same address replaces that invite: still fits.
        again = await owner.post(INVITES, json={"email": "p0@example.com", "role": "admin"})
        assert again.status_code == 201

        # Back to free: nobody is removed, but an old invite can't be accepted any more.
        set_plan(org, None, status="canceled")
        token = world.email.link_token("p1@example.com")
        res = await late.post(
            "/api/invites/signup",
            json={"token": token, "name": "Late", "password": "correct horse battery"},
        )
        assert res.status_code == 402
        members = (await owner.get("/api/organizations/current/members")).json()["items"]
        assert len(members) == 2


async def test_api_key_limit_counts_only_working_keys(world: World) -> None:
    async with world.client() as c:
        await world.signup_and_verify(c, "owner@example.com")
        first = await c.post(KEYS, json={"name": "one", "scopes": ["jobs:read"]})
        assert first.status_code == 201
        second = await c.post(KEYS, json={"name": "two", "scopes": ["jobs:read"]})
        assert second.status_code == 402
        assert "allows 1 API key" in second.json()["error"]["message"]

        await c.delete(f"{KEYS}/{first.json()['id']}")  # revoked keys don't count
        third = await c.post(KEYS, json={"name": "three", "scopes": ["jobs:read"]})
        assert third.status_code == 201
        with sync_session() as s:  # nor do expired ones
            s.execute(
                update(ApiKey)
                .where(ApiKey.id == uuid.UUID(third.json()["id"]))
                .values(expires_at=datetime.now(UTC) - timedelta(days=1))
            )
        assert (
            await c.post(KEYS, json={"name": "four", "scopes": ["jobs:read"]})
        ).status_code == 201


async def test_parallel_key_creation_cannot_pass_the_limit(world: World) -> None:
    async with world.client() as c:
        await world.signup_and_verify(c, "owner@example.com")
        results = await asyncio.gather(
            *(c.post(KEYS, json={"name": f"k{i}", "scopes": ["jobs:read"]}) for i in range(6))
        )
        assert sorted(r.status_code for r in results) == [201] + [402] * 5


async def test_limits_are_per_workspace(world: World) -> None:
    async with world.client() as a, world.client() as b:
        me_a = await world.signup_and_verify(a, "a@example.com")
        await world.signup_and_verify(b, "b@example.com")
        _set_usage(me_a["active_organization_id"], 50)
        assert (await _job(a)).status_code == 402
        assert (await _job(b)).status_code == 202
        assert (await a.post(KEYS, json={"name": "k", "scopes": ["jobs:read"]})).status_code == 201
        assert (await b.post(KEYS, json={"name": "k", "scopes": ["jobs:read"]})).status_code == 201


def test_month_helpers() -> None:
    assert month_start(datetime(2026, 12, 31, 23, 59, tzinfo=UTC)) == date(2026, 12, 1)
    assert next_month_start(datetime(2026, 12, 15, tzinfo=UTC)) == date(2027, 1, 1)
    assert next_month_start(datetime(2026, 1, 31, tzinfo=UTC)) == date(2026, 2, 1)
