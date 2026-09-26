"""Audit log: what gets recorded, who sees it, paging and filters."""

import pytest

from tests.helpers import World, build_world

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_db")]

AUDIT = "/api/organizations/current/audit-log"


@pytest.fixture
def world() -> World:
    return build_world()


async def test_team_changes_are_recorded_with_actor_and_ip(world: World) -> None:
    async with world.client(**{"user-agent": "pytest-browser"}) as owner, world.client() as m:
        await world.signup_and_verify(owner, "owner@example.com", "Olga")
        await owner.patch("/api/organizations/current", json={"name": "Acme"})
        await world.invite_and_join(owner, m, "m@example.com", name="Max")
        member_id = (await m.get("/api/auth/me")).json()["user"]["id"]
        await owner.patch(f"/api/organizations/current/members/{member_id}", json={"role": "admin"})
        key = (
            await owner.post(
                "/api/organizations/current/api-keys", json={"name": "k", "scopes": ["jobs:read"]}
            )
        ).json()
        await owner.delete(f"/api/organizations/current/api-keys/{key['id']}")

        page = (await owner.get(AUDIT)).json()
        actions = [e["action"] for e in page["items"]]
        assert actions == [
            "api_key.revoked",
            "api_key.created",
            "member.role_changed",
            "member.joined",
            "invite.created",
            "org.renamed",
            "org.created",
        ]
        by_action = {e["action"]: e for e in page["items"]}
        changed = by_action["member.role_changed"]
        assert changed["actor"] == {"type": "user", "name": "Olga", "email": "owner@example.com"}
        assert changed["details"] == {"email": "m@example.com", "from": "member", "to": "admin"}
        assert changed["target_id"] == member_id
        assert changed["ip_address"]
        assert by_action["member.joined"]["actor"]["name"] == "Max"
        assert by_action["org.renamed"]["details"] == {"from": "Olga's workspace", "to": "Acme"}
        # Secrets never go into the log.
        assert key["key"] not in str(page)

        # Sign-ins are account events: not in the workspace log.
        assert "auth.login" not in actions


async def test_paging_and_filter(world: World) -> None:
    async with world.client() as owner:
        await world.signup_and_verify(owner, "owner@example.com")
        for i in range(5):
            await owner.post(
                "/api/organizations/current/invites", json={"email": f"{i}@example.com"}
            )
        first = (await owner.get(AUDIT, params={"limit": 4})).json()
        assert len(first["items"]) == 4 and first["next_cursor"]
        second = (
            await owner.get(AUDIT, params={"limit": 4, "before": first["next_cursor"]})
        ).json()
        assert len(second["items"]) == 2 and second["next_cursor"] is None
        ids = [e["id"] for e in first["items"] + second["items"]]
        assert len(set(ids)) == 6

        invites = (await owner.get(AUDIT, params={"action": "invite"})).json()["items"]
        assert len(invites) == 5 and {e["action"] for e in invites} == {"invite.created"}
        exact = (await owner.get(AUDIT, params={"action": "org.created"})).json()["items"]
        assert len(exact) == 1
        # "invite" must not match "invitex.*"-like actions; prefixes stop at the dot.
        assert (await owner.get(AUDIT, params={"action": "inv"})).json()["items"] == []

        bad = await owner.get(AUDIT, params={"before": "not-a-cursor"})
        assert bad.status_code == 400
        assert bad.json()["error"]["code"] == "invalid_cursor"
        assert (await owner.get(AUDIT, params={"action": "DROP TABLE"})).status_code == 422


async def test_each_workspace_sees_only_its_own_log(world: World) -> None:
    async with world.client() as alice, world.client() as bob:
        await world.signup_and_verify(alice, "alice@example.com")
        await world.signup_and_verify(bob, "bob@example.com")
        await alice.post("/api/organizations/current/invites", json={"email": "x@example.com"})
        bob_actions = [e["action"] for e in (await bob.get(AUDIT)).json()["items"]]
        assert bob_actions == ["org.created"]
