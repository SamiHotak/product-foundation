"""Profile and password of the signed-in person, end to end against real Postgres."""

import pytest

from app.services.google_oauth import GoogleProfile
from tests.helpers import PASSWORD, World, build_world

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_db")]

PROFILE = "/api/account/profile"
PASSWORD_URL = "/api/account/password"
NEW_PASSWORD = "a much better passphrase"


@pytest.fixture
def world() -> World:
    return build_world()


async def test_change_name(world: World) -> None:
    async with world.client() as c:
        await world.signup_and_verify(c, "ezat@example.com", "Ezat")
        res = await c.patch(PROFILE, json={"name": "  Ezat Hotak  "})
        assert res.status_code == 200, res.text
        assert res.json()["name"] == "Ezat Hotak"
        me = (await c.get("/api/auth/me")).json()
        assert me["user"]["name"] == "Ezat Hotak"
        # The team sees the new name too.
        members = (await c.get("/api/organizations/current/members")).json()["items"]
        assert members[0]["name"] == "Ezat Hotak"


@pytest.mark.parametrize("name", ["", "   ", "x" * 121])
async def test_name_is_validated(world: World, name: str) -> None:
    async with world.client() as c:
        await world.signup_and_verify(c, "ezat@example.com")
        res = await c.patch(PROFILE, json={"name": name})
        assert res.status_code == 422
        assert res.json()["error"]["code"] == "validation_error"


async def test_profile_needs_sign_in_and_rejects_unknown_fields(world: World) -> None:
    async with world.client() as c:
        assert (await c.patch(PROFILE, json={"name": "X"})).status_code == 401
        await world.signup_and_verify(c, "ezat@example.com")
        # The email can't be changed here (it needs its own verification flow).
        res = await c.patch(PROFILE, json={"name": "X", "email": "evil@example.com"})
        assert res.status_code == 422


async def test_change_password_signs_out_other_browsers(world: World) -> None:
    async with world.client() as laptop, world.client() as phone, world.client() as fresh:
        await world.signup_and_verify(laptop, "ezat@example.com")
        res = await phone.post(
            "/api/auth/login", json={"email": "ezat@example.com", "password": PASSWORD}
        )
        assert res.status_code == 200

        res = await laptop.put(
            PASSWORD_URL, json={"current_password": PASSWORD, "new_password": NEW_PASSWORD}
        )
        assert res.status_code == 200, res.text
        assert res.json()["has_password"] is True

        # This browser stays in; the other one is out.
        assert (await laptop.get("/api/auth/me")).status_code == 200
        assert (await phone.get("/api/auth/me")).status_code == 401
        # Old password no longer works, the new one does.
        old = await fresh.post(
            "/api/auth/login", json={"email": "ezat@example.com", "password": PASSWORD}
        )
        assert old.status_code == 401
        new = await fresh.post(
            "/api/auth/login", json={"email": "ezat@example.com", "password": NEW_PASSWORD}
        )
        assert new.status_code == 200


async def test_wrong_current_password_is_refused_and_locked(world: World) -> None:
    settings = world.settings(login_max_failures=3)
    async with world.client() as c:
        await world.signup_and_verify(c, "ezat@example.com")
        body = {"current_password": "not my password", "new_password": NEW_PASSWORD}
        for _ in range(settings.login_max_failures):
            res = await c.put(PASSWORD_URL, json=body)
            assert res.status_code == 400
            assert res.json()["error"]["code"] == "wrong_password"
        # Now even the right password is refused for a while (no guessing through here).
        res = await c.put(
            PASSWORD_URL, json={"current_password": PASSWORD, "new_password": NEW_PASSWORD}
        )
        assert res.status_code == 429
        assert "retry_after" in res.json()["error"]["details"]


async def test_missing_current_password_is_refused(world: World) -> None:
    async with world.client() as c:
        await world.signup_and_verify(c, "ezat@example.com")
        res = await c.put(PASSWORD_URL, json={"new_password": NEW_PASSWORD})
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "wrong_password"


async def test_new_password_must_be_long_enough(world: World) -> None:
    async with world.client() as c:
        await world.signup_and_verify(c, "ezat@example.com")
        res = await c.put(
            PASSWORD_URL, json={"current_password": PASSWORD, "new_password": "short"}
        )
        assert res.status_code == 422


async def test_google_only_account_sets_a_first_password(world: World) -> None:
    world.google.profile = GoogleProfile(
        sub="g-1", email="gina@example.com", email_verified=True, name="Gina"
    )
    async with world.client() as c:
        start = await c.get("/api/auth/google/start")
        state = start.headers["location"].split("state=")[1].split("&")[0]
        res = await c.get(f"/api/auth/google/callback?code=abc&state={state}")
        assert res.status_code == 303
        me = (await c.get("/api/auth/me")).json()
        assert me["user"]["has_password"] is False

        res = await c.put(PASSWORD_URL, json={"new_password": NEW_PASSWORD})
        assert res.status_code == 200, res.text
        assert res.json()["has_password"] is True
        assert res.json()["google_linked"] is True

    async with world.client() as other:
        res = await other.post(
            "/api/auth/login", json={"email": "gina@example.com", "password": NEW_PASSWORD}
        )
        assert res.status_code == 200
