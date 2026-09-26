"""Auth flows end to end against real Postgres (email, rate limits and Google are fakes)."""

import pytest
from sqlalchemy import select

from app.db.session import get_async_engine
from app.models.user import User
from app.services.google_oauth import GoogleAuthError, GoogleProfile
from tests.helpers import PASSWORD, World, build_world

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_db")]


@pytest.fixture
def world() -> World:
    return build_world()


async def _user(email: str) -> User | None:
    from sqlalchemy.ext.asyncio import AsyncSession

    async with AsyncSession(get_async_engine()) as s:
        found: User | None = await s.scalar(select(User).where(User.email == email))
        return found


# --- sign up + verify -------------------------------------------------------------------


async def test_signup_verify_signs_in_and_creates_workspace(world: World) -> None:
    async with world.client() as c:
        res = await c.post(
            "/api/auth/signup",
            json={"name": "Ezat Hotak", "email": "Ezat@Example.com", "password": PASSWORD},
        )
        assert res.status_code == 202
        assert (await c.get("/api/auth/me")).status_code == 401  # not signed in yet

        mail = world.email.last_to("ezat@example.com")
        assert "Confirm your email" in mail.subject
        assert "http://localhost:3000/verify-email?token=" in mail.text

        res = await c.post(
            "/api/auth/verify-email", json={"token": world.email.link_token("ezat@example.com")}
        )
        assert res.status_code == 200, res.text
        me = res.json()
        assert me["user"]["email_verified"] is True
        assert [o["name"] for o in me["organizations"]] == ["Ezat's workspace"]
        assert me["organizations"][0]["role"] == "owner"
        assert me["active_organization_id"] == me["organizations"][0]["id"]

        cookie = res.headers["set-cookie"].lower()
        assert "httponly" in cookie and "samesite=lax" in cookie and "path=/" in cookie
        me2 = (await c.get("/api/auth/me")).json()
        assert me2["user"]["email"] == "Ezat@example.com"  # domain is normalized


async def test_verification_link_works_only_once(world: World) -> None:
    async with world.client() as c:
        await c.post(
            "/api/auth/signup", json={"name": "A", "email": "a@example.com", "password": PASSWORD}
        )
        token = world.email.link_token("a@example.com")
        assert (await c.post("/api/auth/verify-email", json={"token": token})).status_code == 200
        again = await c.post("/api/auth/verify-email", json={"token": token})
        assert again.status_code == 400
        assert again.json()["error"]["code"] == "invalid_token"


async def test_resend_cancels_the_old_link(world: World) -> None:
    async with world.client() as c:
        await c.post(
            "/api/auth/signup", json={"name": "A", "email": "a@example.com", "password": PASSWORD}
        )
        old = world.email.link_token("a@example.com")
        assert (
            await c.post("/api/auth/resend-verification", json={"email": "a@example.com"})
        ).status_code == 202
        new = world.email.link_token("a@example.com")
        assert old != new
        assert (await c.post("/api/auth/verify-email", json={"token": old})).status_code == 400
        assert (await c.post("/api/auth/verify-email", json={"token": new})).status_code == 200


async def test_signup_does_not_reveal_existing_accounts(world: World) -> None:
    async with world.client() as c:
        await world.signup_and_verify(c, "taken@example.com")
    async with world.client() as other:
        res = await other.post(
            "/api/auth/signup",
            json={
                "name": "Mallory",
                "email": "taken@example.com",
                "password": "another password 1",
            },
        )
    assert res.status_code == 202  # same answer as a new sign-up
    assert "already have" in world.email.last_to("taken@example.com").subject
    user = await _user("taken@example.com")
    assert user is not None and user.name == "Ezat Test"  # nothing changed


async def test_signup_validates_input(world: World) -> None:
    async with world.client() as c:
        short = await c.post(
            "/api/auth/signup", json={"name": "A", "email": "a@example.com", "password": "short"}
        )
        bad_email = await c.post(
            "/api/auth/signup", json={"name": "A", "email": "nope", "password": PASSWORD}
        )
    assert short.status_code == 422 and bad_email.status_code == 422


# --- login / logout ---------------------------------------------------------------------


async def test_login_and_logout(world: World) -> None:
    async with world.client() as c:
        await world.signup_and_verify(c, "a@example.com")
        assert (await c.post("/api/auth/logout")).status_code == 204
        assert (await c.get("/api/auth/me")).status_code == 401
        res = await c.post("/api/auth/login", json={"email": "A@EXAMPLE.COM", "password": PASSWORD})
        assert res.status_code == 200, res.text
        assert (await c.get("/api/auth/me")).status_code == 200


async def test_login_gives_a_new_session_each_time(world: World) -> None:
    async with world.client() as c:
        await world.signup_and_verify(c, "a@example.com")
        first = c.cookies.get("session")
        await c.post("/api/auth/login", json={"email": "a@example.com", "password": PASSWORD})
        assert c.cookies.get("session") != first


async def test_logout_really_ends_the_session(world: World) -> None:
    async with world.client() as c:
        await world.signup_and_verify(c, "a@example.com")
        stolen = c.cookies.get("session")
        await c.post("/api/auth/logout")
    async with world.client() as attacker:
        attacker.cookies.set("session", stolen or "")
        assert (await attacker.get("/api/auth/me")).status_code == 401


async def test_wrong_password_and_unknown_email_look_the_same(world: World) -> None:
    async with world.client() as c:
        await world.signup_and_verify(c, "a@example.com")
    async with world.client() as c:
        wrong = await c.post(
            "/api/auth/login", json={"email": "a@example.com", "password": "wrong password"}
        )
        unknown = await c.post(
            "/api/auth/login", json={"email": "nobody@example.com", "password": "wrong password"}
        )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["error"]["message"] == unknown.json()["error"]["message"]


async def test_unverified_account_cannot_sign_in(world: World) -> None:
    async with world.client() as c:
        await c.post(
            "/api/auth/signup", json={"name": "A", "email": "a@example.com", "password": PASSWORD}
        )
        res = await c.post("/api/auth/login", json={"email": "a@example.com", "password": PASSWORD})
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "email_not_verified"


async def test_brute_force_lock_after_5_failures(world: World) -> None:
    async with world.client() as c:
        await world.signup_and_verify(c, "a@example.com")
    async with world.client() as c:
        for _ in range(5):
            res = await c.post(
                "/api/auth/login", json={"email": "a@example.com", "password": "guess guess"}
            )
            assert res.status_code == 401
        locked = await c.post(
            "/api/auth/login", json={"email": "a@example.com", "password": PASSWORD}
        )
    assert locked.status_code == 429  # even the right password waits
    assert int(locked.headers["Retry-After"]) > 0
    assert locked.json()["error"]["code"] == "too_many_requests"


async def test_per_ip_limit(world: World) -> None:
    async with world.client() as c:
        codes = [
            (
                await c.post("/api/auth/forgot-password", json={"email": f"x{i}@example.com"})
            ).status_code
            for i in range(21)
        ]
    assert codes[:20] == [202] * 20
    assert codes[20] == 429


# --- password reset ---------------------------------------------------------------------


async def test_password_reset_signs_out_everywhere(world: World) -> None:
    async with world.client() as laptop:
        await world.signup_and_verify(laptop, "a@example.com")
        async with world.client() as phone:
            res = await phone.post("/api/auth/forgot-password", json={"email": "a@example.com"})
            assert res.status_code == 202
            token = world.email.link_token("a@example.com")
            assert "reset-password?token=" in world.email.last_to("a@example.com").text
            res = await phone.post(
                "/api/auth/reset-password", json={"token": token, "password": "new password 123"}
            )
            assert res.status_code == 200, res.text
            assert (
                await phone.get("/api/auth/me")
            ).status_code == 200  # signed in with the new session
        assert (await laptop.get("/api/auth/me")).status_code == 401  # old session ended
        old = await laptop.post(
            "/api/auth/login", json={"email": "a@example.com", "password": PASSWORD}
        )
        new = await laptop.post(
            "/api/auth/login", json={"email": "a@example.com", "password": "new password 123"}
        )
    assert old.status_code == 401 and new.status_code == 200
    async with world.client() as c:
        reuse = await c.post(
            "/api/auth/reset-password", json={"token": token, "password": "third password 1"}
        )
    assert reuse.status_code == 400


async def test_forgot_password_for_unknown_email_sends_nothing(world: World) -> None:
    async with world.client() as c:
        res = await c.post("/api/auth/forgot-password", json={"email": "nobody@example.com"})
    assert res.status_code == 202
    assert world.email.sent == []


async def test_inbox_flooding_is_limited(world: World) -> None:
    async with world.client() as c:
        await world.signup_and_verify(c, "a@example.com")
    before = len(world.email.sent)
    world.limiter = world.limiter  # same limiter; IP limit is 20/min, email limit 5/hour
    async with world.client() as c:
        for _ in range(8):
            await c.post("/api/auth/forgot-password", json={"email": "a@example.com"})
    assert len(world.email.sent) - before <= 5


# --- CSRF -------------------------------------------------------------------------------


async def test_cross_site_post_with_session_cookie_is_blocked(world: World) -> None:
    async with world.client() as c:
        await world.signup_and_verify(c, "a@example.com")
        evil = await c.post(
            "/api/organizations", json={"name": "X"}, headers={"Origin": "https://evil.example"}
        )
        ours = await c.post(
            "/api/organizations", json={"name": "X"}, headers={"Origin": "http://localhost:3000"}
        )
    assert evil.status_code == 403
    assert evil.json()["error"]["code"] == "csrf_failed"
    assert ours.status_code == 201


# --- Google -----------------------------------------------------------------------------


async def _google_login(world: World, c: object, profile: GoogleProfile) -> object:
    from httpx import AsyncClient

    assert isinstance(c, AsyncClient)
    world.google.profile = profile
    start = await c.get("/api/auth/google/start")
    assert start.status_code == 303
    state = start.headers["location"].split("state=")[1].split("&")[0]
    return await c.get(f"/api/auth/google/callback?code=abc&state={state}")


async def test_google_creates_account_and_signs_in(world: World) -> None:
    async with world.client() as c:
        res = await _google_login(
            world,
            c,
            GoogleProfile(
                sub="g-1", email="g@example.com", email_verified=True, name="Gina Google"
            ),
        )
        assert res.status_code == 303 and res.headers["location"] == "/dashboard"  # type: ignore[attr-defined]
        me = (await c.get("/api/auth/me")).json()
    assert me["user"]["google_linked"] is True and me["user"]["has_password"] is False
    assert me["organizations"][0]["name"] == "Gina's workspace"
    assert world.google.last_verifier  # PKCE verifier was sent


async def test_google_rejects_wrong_state(world: World) -> None:
    async with world.client() as c:
        world.google.profile = GoogleProfile(
            sub="g-1", email="g@example.com", email_verified=True, name="G"
        )
        await c.get("/api/auth/google/start")
        res = await c.get("/api/auth/google/callback?code=abc&state=forged-state")
        assert res.headers["location"] == "/login?error=google"
        assert (await c.get("/api/auth/me")).status_code == 401


async def test_google_requires_verified_email(world: World) -> None:
    async with world.client() as c:
        res = await _google_login(
            world,
            c,
            GoogleProfile(sub="g-1", email="g@example.com", email_verified=False, name="G"),
        )
        assert res.headers["location"] == "/login?error=google"  # type: ignore[attr-defined]


async def test_google_error_goes_back_to_login(world: World) -> None:
    world.google.error = GoogleAuthError("boom")
    async with world.client() as c:
        start = await c.get("/api/auth/google/start")
        state = start.headers["location"].split("state=")[1].split("&")[0]
        world.google.profile = None
        res = await c.get(f"/api/auth/google/callback?code=abc&state={state}")
    assert res.headers["location"] == "/login?error=google"


async def test_google_links_to_verified_account(world: World) -> None:
    async with world.client() as c:
        await world.signup_and_verify(c, "a@example.com")
    async with world.client() as c:
        await _google_login(
            world, c, GoogleProfile(sub="g-9", email="A@example.com", email_verified=True, name="A")
        )
        me = (await c.get("/api/auth/me")).json()
    assert me["user"]["google_linked"] is True and me["user"]["has_password"] is True
    assert len(me["organizations"]) == 1  # same account, no second workspace


async def test_google_takeover_of_unverified_account_removes_attacker_password(
    world: World,
) -> None:
    async with world.client() as attacker:
        await attacker.post(
            "/api/auth/signup",
            json={"name": "Mallory", "email": "victim@example.com", "password": "attacker pass 1"},
        )
    async with world.client() as victim:
        await _google_login(
            world,
            victim,
            GoogleProfile(
                sub="g-v", email="victim@example.com", email_verified=True, name="Victim"
            ),
        )
    async with world.client() as attacker:
        res = await attacker.post(
            "/api/auth/login", json={"email": "victim@example.com", "password": "attacker pass 1"}
        )
    assert res.status_code == 401


async def test_providers_endpoint(world: World) -> None:
    async with world.client() as c:
        res = await c.get("/api/auth/providers")
    assert res.json() == {"password": True, "google": False}  # no Google keys in tests


# --- workspaces ---------------------------------------------------------------------------


async def test_create_and_switch_workspace(world: World) -> None:
    async with world.client() as c:
        me = await world.signup_and_verify(c, "a@example.com")
        first = me["active_organization_id"]
        created = await c.post("/api/organizations", json={"name": "Client project"})
        assert created.status_code == 201
        me = (await c.get("/api/auth/me")).json()
        assert me["active_organization_id"] == created.json()["id"]  # new one is active
        assert {o["name"] for o in me["organizations"]} == {"Ezat's workspace", "Client project"}
        res = await c.put("/api/auth/session/organization", json={"organization_id": first})
        assert res.status_code == 200 and res.json()["active_organization_id"] == first


async def test_google_returns_to_a_safe_next_page(world: World) -> None:
    """E.g. "Continue with Google" on the invite page comes back to the invite page."""
    profile = GoogleProfile(sub="g-2", email="n@example.com", email_verified=True, name="N")
    async with world.client() as c:
        world.google.profile = profile
        start = await c.get("/api/auth/google/start?next=/invite%3Ftoken%3Dabc")
        state = start.headers["location"].split("state=")[1].split("&")[0]
        res = await c.get(f"/api/auth/google/callback?code=abc&state={state}")
        assert res.headers["location"] == "/invite?token=abc"
    async with world.client() as c:
        start = await c.get("/api/auth/google/start?next=//evil.example")
        assert "google_next" not in start.headers.get("set-cookie", "")
        state = start.headers["location"].split("state=")[1].split("&")[0]
        res = await c.get(f"/api/auth/google/callback?code=abc&state={state}")
        assert res.headers["location"] == "/dashboard"
