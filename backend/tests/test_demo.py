"""Demo mode: "Try the demo" signs into a seeded, read-mostly workspace; nightly reset."""

import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.db.session import sync_session
from app.models.file import StoredFile
from app.models.user import User
from app.services.demo import DEMO_WORKSPACE, SAMPLE_FILES, TEAM, reset_demo_data, seed_demo
from app.workers import tasks
from tests.helpers import World, build_world

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_db")]


@pytest.fixture
def world() -> World:
    return build_world(demo_enabled=True)


async def test_demo_is_hidden_unless_enabled() -> None:
    world = build_world()
    async with world.client() as c:
        assert (await c.get("/api/auth/providers")).json()["demo"] is False
        assert (await c.post("/api/auth/demo")).status_code == 404


async def test_try_the_demo(world: World) -> None:
    from unittest.mock import patch

    async with world.client() as c:
        assert (await c.get("/api/auth/providers")).json()["demo"] is True
        with patch("app.routers.auth.storage_for", lambda _s: world.storage):
            res = await c.post("/api/auth/demo")
        assert res.status_code == 200, res.text
        me = res.json()
        assert me["user"]["is_demo"] is True
        assert me["organizations"][0]["name"] == DEMO_WORKSPACE
        assert me["organizations"][0]["role"] == "owner"

        members = (await c.get("/api/organizations/current/members")).json()["items"]
        assert len(members) == 1 + len(TEAM)
        files = (await c.get("/api/files")).json()["items"]
        assert len(files) == len(SAMPLE_FILES) and len(world.storage.objects) == len(SAMPLE_FILES)
        jobs = (await c.get("/api/jobs")).json()["items"]
        assert {j["status"] for j in jobs} == {"done", "failed"}
        billing = (await c.get("/api/billing/current")).json()
        assert billing["plan_id"] == "pro"
        assert (await c.get("/api/organizations/current/audit-log")).status_code == 200

        # Read-mostly: harmless actions work ...
        assert (await c.post("/api/jobs/example", json={"steps": 1})).status_code == 202
        assert (await c.post(f"/api/files/{files[0]['id']}/download")).status_code == 200
        status = (await c.get("/api/ai/status")).json()
        assert status["samples_only"] is True
        res = await c.post("/api/ai/summaries", json={"text": status["sample_text"]})
        assert res.status_code == 202, res.text
        # Visitors share one account: their own texts would be seen by the next visitor.
        res = await c.post("/api/ai/summaries", json={"text": "My private notes, long enough."})
        assert res.status_code == 403 and "sample text" in res.text
        # ... changes don't.
        for method, path, body in [
            (
                "post",
                "/api/organizations/current/invites",
                {"email": "x@example.com", "role": "member"},
            ),
            ("patch", "/api/organizations/current", {"name": "Hacked"}),
            ("delete", f"/api/files/{files[0]['id']}", None),
            ("post", "/api/files/uploads", {"filename": "a.pdf", "size_bytes": 10}),
            ("post", "/api/billing/checkout", {"plan_id": "business"}),
            ("post", "/api/organizations", {"name": "Mine"}),
        ]:
            kwargs = {"json": body} if body is not None else {}
            res = await getattr(c, method)(path, **kwargs)
            assert res.status_code == 403, (path, res.text)
            assert res.json()["error"]["code"] == "demo_read_only"

        # Clicking again reuses the same data (no second workspace).
        with patch("app.routers.auth.storage_for", lambda _s: world.storage):
            again = (await c.post("/api/auth/demo")).json()
        assert again["active_organization_id"] == me["active_organization_id"]
        assert (await c.post("/api/auth/logout")).status_code == 204


async def test_nobody_else_can_sign_in_as_the_demo_user(world: World) -> None:
    settings = get_settings()
    seed_demo(settings)
    async with world.client() as c:
        res = await c.post(
            "/api/auth/login", json={"email": settings.demo_email, "password": "anything-at-all"}
        )
        assert res.status_code == 401
        await c.post("/api/auth/forgot-password", json={"email": settings.demo_email})
        assert world.email.sent == []


async def test_nightly_reset_restores_the_data_and_signs_visitors_out(world: World) -> None:
    from unittest.mock import patch

    settings = get_settings()
    async with world.client() as c:
        with patch("app.routers.auth.storage_for", lambda _s: world.storage):
            first = (await c.post("/api/auth/demo")).json()
        await c.post("/api/jobs/example", json={"steps": 1})
        counts = reset_demo_data(settings, world.storage)
        assert counts == {"workspaces": 1, "users": 1 + len(TEAM), "files": len(SAMPLE_FILES)}
        assert (await c.get("/api/auth/me")).status_code == 401
        with patch("app.routers.auth.storage_for", lambda _s: world.storage):
            second = (await c.post("/api/auth/demo")).json()
        assert second["active_organization_id"] != first["active_organization_id"]
        assert len((await c.get("/api/jobs")).json()["items"]) == 7  # the example job is gone
    with sync_session() as s:
        assert s.scalar(select(func.count()).select_from(User).where(User.is_demo)) == 1 + len(TEAM)
        assert s.scalar(select(func.count()).select_from(StoredFile)) == len(SAMPLE_FILES)
    # The nightly task does nothing while the demo is off.
    assert tasks.reset_demo.apply().get() == {"skipped": True}


async def test_a_real_account_with_a_demo_address_is_never_touched(world: World) -> None:
    async with world.client() as c:
        await world.signup_and_verify(c, TEAM[0].email, "Real Mia")
        seed_demo(get_settings())
        with sync_session() as s:
            real = s.scalar(select(User).where(User.email == TEAM[0].email))
            assert real is not None and not real.is_demo
        reset_demo_data(get_settings())
        assert (await c.get("/api/auth/me")).status_code == 200
    settings = get_settings().model_copy(update={"demo_email": TEAM[0].email})
    with pytest.raises(RuntimeError, match="real account"):
        seed_demo(settings)
    # The button then fails safely instead of signing a visitor into Mia's account.
    misconfigured = build_world(demo_enabled=True, demo_email=TEAM[0].email)
    async with misconfigured.client() as visitor:
        res = await visitor.post("/api/auth/demo")
        assert res.status_code == 503
        assert (await visitor.get("/api/auth/me")).status_code == 401


async def test_demo_ai_is_limited_per_visitor() -> None:
    from unittest.mock import patch

    world = build_world(demo_enabled=True, demo_ai_per_hour=2)
    async with world.client() as c:
        with patch("app.routers.auth.storage_for", lambda _s: world.storage):
            assert (await c.post("/api/auth/demo")).status_code == 200
        sample = (await c.get("/api/ai/status")).json()["sample_text"]
        for _ in range(2):
            assert (await c.post("/api/ai/summaries", json={"text": sample})).status_code == 202
        res = await c.post("/api/ai/summaries", json={"text": sample})
        assert res.status_code == 429 and "per hour" in res.text


async def test_switching_the_demo_off_ends_demo_sessions() -> None:
    from unittest.mock import patch

    world = build_world(demo_enabled=True)
    async with world.client() as c:
        with patch("app.routers.auth.storage_for", lambda _s: world.storage):
            assert (await c.post("/api/auth/demo")).status_code == 200
        assert (await c.get("/api/auth/me")).status_code == 200
        off = get_settings().model_copy(update={"demo_enabled": False})
        world.app.dependency_overrides[get_settings] = lambda: off
        assert (await c.get("/api/auth/me")).status_code == 401
