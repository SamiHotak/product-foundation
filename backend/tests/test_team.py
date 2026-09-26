"""Invites, roles and member management, end to end against real Postgres."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import update

from app.db.session import sync_session
from app.models.invite import Invite
from tests.helpers import PASSWORD, World, build_world

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_db")]

INVITES = "/api/organizations/current/invites"
MEMBERS = "/api/organizations/current/members"


@pytest.fixture
def world() -> World:
    return build_world()


def _role_of(me: dict[str, Any], org_id: str) -> str:
    return str(next(o["role"] for o in me["organizations"] if o["id"] == org_id))


# --- invites -----------------------------------------------------------------------------


async def test_invite_new_person_who_creates_account_from_link(world: World) -> None:
    async with world.client() as owner, world.client() as newbie:
        me = await world.signup_and_verify(owner, "owner@example.com", "Olga Owner")
        org_id = me["active_organization_id"]

        res = await owner.post(INVITES, json={"email": "Nina@Example.com", "role": "member"})
        assert res.status_code == 201, res.text
        assert res.json()["invited_by_name"] == "Olga Owner"

        mail = world.email.last_to("nina@example.com")
        assert "Olga Owner invited you" in mail.subject
        assert "http://localhost:3000/invite?token=" in mail.text
        token = world.email.link_token("nina@example.com")

        preview = (await newbie.post("/api/invites/preview", json={"token": token})).json()
        assert preview["organization_name"] == "Olga's workspace"
        assert preview["role"] == "member"
        assert preview["account_exists"] is False

        res = await newbie.post(
            "/api/invites/signup", json={"token": token, "name": "Nina", "password": PASSWORD}
        )
        assert res.status_code == 200, res.text
        joined = res.json()
        # Signed in straight into the team's workspace; no extra personal workspace.
        assert joined["active_organization_id"] == org_id
        assert [o["id"] for o in joined["organizations"]] == [org_id]
        assert joined["user"]["email_verified"] is True
        assert "members:invite" not in joined["permissions"]
        assert (await newbie.get("/api/auth/me")).status_code == 200

        # The link works once.
        again = await newbie.post("/api/invites/preview", json={"token": token})
        assert again.status_code == 400
        assert again.json()["error"]["code"] == "invalid_invite"

        members = (await owner.get(MEMBERS)).json()["items"]
        assert [(m["email"], m["role"]) for m in members] == [
            ("owner@example.com", "owner"),
            ("Nina@example.com", "member"),
        ]
        assert (await owner.get(INVITES)).json()["items"] == []


async def test_existing_user_signs_in_and_accepts(world: World) -> None:
    async with world.client() as owner, world.client() as bob:
        me = await world.signup_and_verify(owner, "owner@example.com", "Olga")
        await world.signup_and_verify(bob, "bob@example.com", "Bob")
        await owner.post(INVITES, json={"email": "bob@example.com", "role": "admin"})
        token = world.email.link_token("bob@example.com")

        preview = (await bob.post("/api/invites/preview", json={"token": token})).json()
        assert preview["account_exists"] is True
        # Creating a second account for the same email is refused.
        dup = await bob.post(
            "/api/invites/signup", json={"token": token, "name": "B", "password": PASSWORD}
        )
        assert dup.status_code == 409
        assert dup.json()["error"]["code"] == "account_exists"

        res = await bob.post("/api/invites/accept", json={"token": token})
        assert res.status_code == 200, res.text
        after = res.json()
        assert after["active_organization_id"] == me["active_organization_id"]
        assert len(after["organizations"]) == 2  # his own + the new one
        assert _role_of(after, me["active_organization_id"]) == "admin"
        assert "members:invite" in after["permissions"]


async def test_invite_is_only_for_the_invited_email(world: World) -> None:
    async with world.client() as owner, world.client() as mallory:
        await world.signup_and_verify(owner, "owner@example.com")
        await world.signup_and_verify(mallory, "mallory@example.com")
        await owner.post(INVITES, json={"email": "friend@example.com"})
        token = world.email.link_token("friend@example.com")
        res = await mallory.post("/api/invites/accept", json={"token": token})
        assert res.status_code == 403
        assert res.json()["error"]["code"] == "invite_email_mismatch"
        # Still usable by the right person.
        assert (
            await mallory.post("/api/invites/preview", json={"token": token})
        ).status_code == 200


async def test_accept_needs_sign_in(world: World) -> None:
    async with world.client() as owner, world.client() as anon:
        await world.signup_and_verify(owner, "owner@example.com")
        await owner.post(INVITES, json={"email": "x@example.com"})
        token = world.email.link_token("x@example.com")
        assert (await anon.post("/api/invites/accept", json={"token": token})).status_code == 401


async def test_unconfirmed_account_is_taken_over_by_invite_signup(world: World) -> None:
    async with world.client() as owner, world.client() as c:
        me = await world.signup_and_verify(owner, "owner@example.com")
        # Someone signed up with this email earlier but never confirmed it.
        await c.post(
            "/api/auth/signup",
            json={"name": "Old", "email": "u@example.com", "password": "an old password"},
        )
        await owner.post(INVITES, json={"email": "u@example.com"})
        token = world.email.link_token("u@example.com")
        assert (await c.post("/api/invites/preview", json={"token": token})).json()[
            "account_exists"
        ] is False
        res = await c.post(
            "/api/invites/signup", json={"token": token, "name": "Uma", "password": PASSWORD}
        )
        assert res.status_code == 200, res.text
        assert res.json()["active_organization_id"] == me["active_organization_id"]
        assert res.json()["user"]["name"] == "Uma"
        # The old password no longer works; the new one does.
        await c.post("/api/auth/logout")
        bad = await c.post(
            "/api/auth/login", json={"email": "u@example.com", "password": "an old password"}
        )
        assert bad.status_code == 401
        good = await c.post(
            "/api/auth/login", json={"email": "u@example.com", "password": PASSWORD}
        )
        assert good.status_code == 200


async def test_reinvite_replaces_old_link_and_revoke_kills_it(world: World) -> None:
    async with world.client() as owner, world.client() as anon:
        await world.signup_and_verify(owner, "owner@example.com")
        await owner.post(INVITES, json={"email": "p@example.com", "role": "member"})
        first = world.email.link_token("p@example.com")
        res = await owner.post(INVITES, json={"email": "p@example.com", "role": "admin"})
        assert res.status_code == 201
        second = world.email.link_token("p@example.com")
        assert first != second
        assert (await anon.post("/api/invites/preview", json={"token": first})).status_code == 400
        preview = (await anon.post("/api/invites/preview", json={"token": second})).json()
        assert preview["role"] == "admin"

        open_invites = (await owner.get(INVITES)).json()["items"]
        assert len(open_invites) == 1
        invite_id = open_invites[0]["id"]

        resent = await owner.post(f"{INVITES}/{invite_id}/resend")
        assert resent.status_code == 200
        third = world.email.link_token("p@example.com")
        assert (await anon.post("/api/invites/preview", json={"token": second})).status_code == 400

        assert (await owner.delete(f"{INVITES}/{invite_id}")).status_code == 204
        assert (await anon.post("/api/invites/preview", json={"token": third})).status_code == 400
        assert (await owner.get(INVITES)).json()["items"] == []
        assert (await owner.delete(f"{INVITES}/{invite_id}")).status_code == 404


async def test_expired_invite_does_not_work(world: World) -> None:
    async with world.client() as owner, world.client() as anon:
        await world.signup_and_verify(owner, "owner@example.com")
        await owner.post(INVITES, json={"email": "late@example.com"})
        token = world.email.link_token("late@example.com")
        with sync_session() as s:
            s.execute(update(Invite).values(expires_at=datetime.now(UTC) - timedelta(minutes=1)))
        res = await anon.post(
            "/api/invites/signup", json={"token": token, "name": "L", "password": PASSWORD}
        )
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "invalid_invite"
        assert (await owner.get(INVITES)).json()["items"] == []  # expired ones aren't listed


async def test_cannot_invite_existing_member_or_as_owner(world: World) -> None:
    async with world.client() as owner, world.client() as m:
        await world.signup_and_verify(owner, "owner@example.com")
        await world.invite_and_join(owner, m, "m@example.com")
        dup = await owner.post(INVITES, json={"email": "M@example.com"})
        assert dup.status_code == 409
        assert "already in this workspace" in dup.json()["error"]["message"]
        as_owner = await owner.post(INVITES, json={"email": "z@example.com", "role": "owner"})
        assert as_owner.status_code == 422


async def test_invites_per_workspace_are_rate_limited(world: World) -> None:
    world.settings(invites_per_org_per_hour=2)
    async with world.client() as owner:
        await world.signup_and_verify(owner, "owner@example.com")
        for i in range(2):
            assert (
                await owner.post(INVITES, json={"email": f"{i}@example.com"})
            ).status_code == 201
        res = await owner.post(INVITES, json={"email": "3@example.com"})
        assert res.status_code == 429
        assert int(res.headers["retry-after"]) > 0


async def test_bad_tokens_are_rejected(world: World) -> None:
    async with world.client() as c:
        res = await c.post("/api/invites/preview", json={"token": "x" * 40})
        assert res.status_code == 400
        assert (await c.post("/api/invites/preview", json={"token": "short"})).status_code == 422


# --- roles and member management ------------------------------------------------------------


async def test_member_role_limits(world: World) -> None:
    async with world.client() as owner, world.client() as member:
        await world.signup_and_verify(owner, "owner@example.com")
        joined = await world.invite_and_join(owner, member, "m@example.com")
        assert set(joined["permissions"]) == {"members:read", "jobs:read", "jobs:write"}
        owner_id = (await owner.get("/api/auth/me")).json()["user"]["id"]

        # A member sees the team ...
        assert (await member.get(MEMBERS)).status_code == 200
        # ... but can't manage it, or anything else admin-only.
        forbidden = [
            ("GET", INVITES, None),
            ("POST", INVITES, {"email": "x@example.com"}),
            ("PATCH", f"{MEMBERS}/{owner_id}", {"role": "member"}),
            ("DELETE", f"{MEMBERS}/{owner_id}", None),
            ("GET", "/api/organizations/current/api-keys", None),
            ("POST", "/api/organizations/current/api-keys", {"name": "k", "scopes": ["jobs:read"]}),
            ("GET", "/api/organizations/current/audit-log", None),
            ("PATCH", "/api/organizations/current", {"name": "Mine now"}),
            ("POST", "/api/organizations/current/transfer-ownership", {"user_id": owner_id}),
            ("POST", "/api/organizations/current/deletion", {"confirm": "x"}),
            ("POST", "/api/organizations/current/exports", None),
        ]
        for method, path, body in forbidden:
            res = await member.request(method, path, json=body)
            assert res.status_code == 403, (method, path, res.status_code, res.text)
            assert res.json()["error"]["code"] == "permission_denied"
        # Using the product is fine.
        assert (await member.post("/api/jobs/example", json={"steps": 1})).status_code == 202


async def test_admin_manages_team_but_not_the_owner(world: World) -> None:
    async with world.client() as owner, world.client() as admin, world.client() as m:
        me = await world.signup_and_verify(owner, "owner@example.com")
        owner_id = me["user"]["id"]
        await world.invite_and_join(owner, admin, "admin@example.com", role="admin")
        # The admin invites a member.
        await world.invite_and_join(admin, m, "m@example.com")
        member_id = (await m.get("/api/auth/me")).json()["user"]["id"]
        admin_id = (await admin.get("/api/auth/me")).json()["user"]["id"]

        promoted = await admin.patch(f"{MEMBERS}/{member_id}", json={"role": "admin"})
        assert promoted.status_code == 200
        assert promoted.json()["role"] == "admin"
        assert "api_keys:manage" in (await m.get("/api/auth/me")).json()["permissions"]

        # The owner is untouchable for admins.
        res = await admin.patch(f"{MEMBERS}/{owner_id}", json={"role": "member"})
        assert res.status_code == 403
        assert (await admin.delete(f"{MEMBERS}/{owner_id}")).status_code == 403
        # Nobody changes their own role.
        own = await admin.patch(f"{MEMBERS}/{admin_id}", json={"role": "member"})
        assert own.status_code == 409
        # Ownership is not a role you can give.
        assert (
            await owner.patch(f"{MEMBERS}/{member_id}", json={"role": "owner"})
        ).status_code == 422
        # Removing yourself goes through "leave".
        assert (await admin.delete(f"{MEMBERS}/{admin_id}")).status_code == 409

        # Remove the member: they lose access to the workspace right away.
        assert (await admin.delete(f"{MEMBERS}/{member_id}")).status_code == 204
        after = (await m.get("/api/auth/me")).json()
        assert me["active_organization_id"] not in [o["id"] for o in after["organizations"]]
        assert after["organizations"][0]["name"] == "New's workspace"  # a fresh personal one
        assert (await admin.delete(f"{MEMBERS}/{member_id}")).status_code == 404


async def test_leave_workspace(world: World) -> None:
    async with world.client() as owner, world.client() as m:
        me = await world.signup_and_verify(owner, "owner@example.com")
        await world.invite_and_join(owner, m, "m@example.com")
        res = await owner.post("/api/organizations/current/leave")
        assert res.status_code == 409
        assert "Transfer ownership" in res.json()["error"]["message"]

        assert (await m.post("/api/organizations/current/leave")).status_code == 204
        after = (await m.get("/api/auth/me")).json()
        assert me["active_organization_id"] not in [o["id"] for o in after["organizations"]]
        emails = [x["email"] for x in (await owner.get(MEMBERS)).json()["items"]]
        assert emails == ["owner@example.com"]


async def test_transfer_ownership(world: World) -> None:
    async with world.client() as owner, world.client() as m:
        me = await world.signup_and_verify(owner, "owner@example.com")
        org_id = me["active_organization_id"]
        await world.invite_and_join(owner, m, "m@example.com")
        member_id = (await m.get("/api/auth/me")).json()["user"]["id"]

        assert (
            await m.post(
                "/api/organizations/current/transfer-ownership", json={"user_id": member_id}
            )
        ).status_code == 403
        res = await owner.post(
            "/api/organizations/current/transfer-ownership", json={"user_id": member_id}
        )
        assert res.status_code == 200, res.text
        roles = {x["email"]: x["role"] for x in res.json()["items"]}
        assert roles == {"owner@example.com": "admin", "m@example.com": "owner"}
        assert _role_of((await owner.get("/api/auth/me")).json(), org_id) == "admin"
        assert "org:delete" in (await m.get("/api/auth/me")).json()["permissions"]
        # The old owner can't do owner things any more, and now may leave.
        again = await owner.post(
            "/api/organizations/current/transfer-ownership", json={"user_id": member_id}
        )
        assert again.status_code == 403
        assert (await owner.post("/api/organizations/current/leave")).status_code == 204


async def test_rename_workspace(world: World) -> None:
    async with world.client() as owner:
        await world.signup_and_verify(owner, "owner@example.com")
        res = await owner.patch("/api/organizations/current", json={"name": "  Acme GmbH  "})
        assert res.status_code == 200
        assert res.json()["name"] == "Acme GmbH"
        assert (
            await owner.patch("/api/organizations/current", json={"name": ""})
        ).status_code == 422


async def test_permissions_in_me_match_the_role(world: World) -> None:
    async with world.client() as owner:
        me = await world.signup_and_verify(owner, "owner@example.com")
        assert {"org:delete", "ownership:transfer", "members:invite"} <= set(me["permissions"])
