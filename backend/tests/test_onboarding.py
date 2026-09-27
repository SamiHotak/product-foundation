"""The "Get started" checklist, end to end against real Postgres."""

from typing import Any

import pytest

from tests.helpers import World, build_world

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_db")]

ONBOARDING = "/api/organizations/current/onboarding"


@pytest.fixture
def world() -> World:
    return build_world()


def _done(status: dict[str, Any]) -> dict[str, bool]:
    return {s["key"]: s["done"] for s in status["steps"]}


async def test_steps_turn_done_as_the_owner_uses_the_app(world: World) -> None:
    async with world.client() as c:
        await world.signup_and_verify(c, "owner@example.com", "Olga")
        status = (await c.get(ONBOARDING)).json()
        assert status["dismissed"] is False
        # Order matters: the UI shows the steps in this order.
        assert [s["key"] for s in status["steps"]] == [
            "verify_email",
            "invite_teammate",
            "create_api_key",
            "run_job",
        ]
        assert _done(status) == {
            "verify_email": True,
            "invite_teammate": False,
            "create_api_key": False,
            "run_job": False,
        }

        await c.post("/api/jobs/example", json={"steps": 1})
        await c.post(
            "/api/organizations/current/api-keys", json={"name": "Zapier", "scopes": ["jobs:read"]}
        )
        await c.post(
            "/api/organizations/current/invites",
            json={"email": "nina@example.com", "role": "member"},
        )
        assert all(_done((await c.get(ONBOARDING)).json()).values())


async def test_private_export_jobs_do_not_count_as_a_job(world: World) -> None:
    async with world.client() as c:
        await world.signup_and_verify(c, "owner@example.com")
        assert (await c.post("/api/account/exports")).status_code == 202
        assert _done((await c.get(ONBOARDING)).json())["run_job"] is False


async def test_members_only_see_steps_they_can_do(world: World) -> None:
    async with world.client() as owner, world.client() as member:
        await world.signup_and_verify(owner, "owner@example.com", "Olga")
        await world.invite_and_join(owner, member, "mia@example.com", "member", "Mia")
        status = (await member.get(ONBOARDING)).json()
        assert [s["key"] for s in status["steps"]] == ["verify_email", "run_job"]


async def test_hide_is_per_person_and_per_workspace_and_can_be_undone(world: World) -> None:
    async with world.client() as owner, world.client() as member:
        await world.signup_and_verify(owner, "owner@example.com", "Olga")
        await world.invite_and_join(owner, member, "mia@example.com", "admin", "Mia")

        res = await owner.post(f"{ONBOARDING}/dismiss")
        assert res.status_code == 200 and res.json()["dismissed"] is True
        assert (await owner.post(f"{ONBOARDING}/dismiss")).json()["dismissed"] is True  # twice ok
        assert (await owner.get(ONBOARDING)).json()["dismissed"] is True
        # Mia still sees it in the same workspace.
        assert (await member.get(ONBOARDING)).json()["dismissed"] is False

        # A new workspace of the owner shows it again.
        created = await owner.post("/api/organizations", json={"name": "Second"})
        assert created.status_code == 201
        assert (await owner.get(ONBOARDING)).json()["dismissed"] is False

        # Undo in the first workspace.
        first = next(
            o["id"]
            for o in (await owner.get("/api/auth/me")).json()["organizations"]
            if o["name"] != "Second"
        )
        await owner.put("/api/auth/session/organization", json={"organization_id": first})
        res = await owner.delete(f"{ONBOARDING}/dismiss")
        assert res.status_code == 200 and res.json()["dismissed"] is False
        assert (await owner.delete(f"{ONBOARDING}/dismiss")).json()["dismissed"] is False


async def test_steps_are_counted_per_workspace(world: World) -> None:
    """Org isolation: another workspace's keys, invites and jobs don't tick your steps."""
    async with world.client() as a, world.client() as b:
        await world.signup_and_verify(a, "a@example.com", "Anna")
        await world.signup_and_verify(b, "b@example.com", "Ben")
        await a.post("/api/jobs/example", json={"steps": 1})
        await a.post(
            "/api/organizations/current/api-keys", json={"name": "K", "scopes": ["jobs:read"]}
        )
        await a.post(
            "/api/organizations/current/invites", json={"email": "x@example.com", "role": "member"}
        )
        assert all(_done((await a.get(ONBOARDING)).json()).values())
        done_b = _done((await b.get(ONBOARDING)).json())
        assert done_b == {
            "verify_email": True,
            "invite_teammate": False,
            "create_api_key": False,
            "run_job": False,
        }


async def test_needs_sign_in(world: World) -> None:
    async with world.client() as c:
        assert (await c.get(ONBOARDING)).status_code == 401
        assert (await c.post(f"{ONBOARDING}/dismiss")).status_code == 401
