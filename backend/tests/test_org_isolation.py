"""Tenant isolation: one organization can never see another organization's data.

Two real users, two workspaces, real Postgres. Every tenant endpoint must pass these.
When a product adds a new tenant table, add its endpoints here.
"""

import uuid

import pytest

from tests.helpers import World, build_world

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_db")]


@pytest.fixture
def world() -> World:
    return build_world()


async def test_users_only_see_their_own_jobs(world: World) -> None:
    async with world.client() as alice, world.client() as bob:
        await world.signup_and_verify(alice, "alice@example.com", "Alice")
        await world.signup_and_verify(bob, "bob@example.com", "Bob")

        job_a = (await alice.post("/api/jobs/example", json={"steps": 1})).json()
        job_b = (await bob.post("/api/jobs/example", json={"steps": 1})).json()

        # Bob can't read Alice's job, not even by guessing its id: it "doesn't exist".
        res = await bob.get(f"/api/jobs/{job_a['id']}")
        assert res.status_code == 404
        assert res.json()["error"]["code"] == "not_found"
        assert (await alice.get(f"/api/jobs/{job_b['id']}")).status_code == 404

        # Lists only contain the caller's own jobs.
        assert [j["id"] for j in (await alice.get("/api/jobs")).json()["items"]] == [job_a["id"]]
        assert [j["id"] for j in (await bob.get("/api/jobs")).json()["items"]] == [job_b["id"]]


async def test_cannot_switch_into_someone_elses_workspace(world: World) -> None:
    async with world.client() as alice, world.client() as bob:
        me_a = await world.signup_and_verify(alice, "alice@example.com", "Alice")
        me_b = await world.signup_and_verify(bob, "bob@example.com", "Bob")
        res = await bob.put(
            "/api/auth/session/organization",
            json={"organization_id": me_a["active_organization_id"]},
        )
        assert res.status_code == 404
        # Still in his own workspace, and still can't see Alice's workspace.
        me = (await bob.get("/api/auth/me")).json()
        assert me["active_organization_id"] == me_b["active_organization_id"]
        assert [o["id"] for o in me["organizations"]] == [me_b["active_organization_id"]]
        orgs = (await bob.get("/api/organizations")).json()
        assert me_a["active_organization_id"] not in [o["id"] for o in orgs]


async def test_jobs_follow_the_active_workspace(world: World) -> None:
    async with world.client() as c:
        await world.signup_and_verify(c, "a@example.com")
        job_1 = (await c.post("/api/jobs/example", json={"steps": 1})).json()
        second = (await c.post("/api/organizations", json={"name": "Second"})).json()
        assert (await c.get("/api/auth/me")).json()["active_organization_id"] == second["id"]
        # In the new workspace, the first workspace's job is invisible.
        assert (await c.get("/api/jobs")).json()["items"] == []
        assert (await c.get(f"/api/jobs/{job_1['id']}")).status_code == 404
    assert world.dispatched[0].organization_id != uuid.UUID(second["id"])


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/auth/me"),
        ("GET", "/api/organizations"),
        ("POST", "/api/organizations"),
        ("GET", "/api/jobs"),
        ("POST", "/api/jobs/example"),
        ("GET", f"/api/jobs/{uuid.uuid4()}"),
        ("PUT", "/api/auth/session/organization"),
    ],
)
async def test_everything_needs_sign_in(world: World, method: str, path: str) -> None:
    async with world.client() as c:
        body = {"name": "x", "organization_id": str(uuid.uuid4())} if method != "GET" else None
        res = await c.request(method, path, json=body)
    assert res.status_code == 401, (method, path, res.status_code)
    assert res.json()["error"]["code"] == "unauthorized"


async def test_forged_session_cookie_is_rejected(world: World) -> None:
    async with world.client() as c:
        c.cookies.set("session", "made-up-token-" + "x" * 30)
        assert (await c.get("/api/jobs")).status_code == 401
