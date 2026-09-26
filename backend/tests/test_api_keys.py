"""API keys: create, use with the public REST API, scopes, revoke, expiry, limits."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update

from app.db.session import sync_session
from app.models.api_key import ApiKey
from tests.helpers import World, build_world

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_db")]

KEYS = "/api/organizations/current/api-keys"


@pytest.fixture
def world() -> World:
    return build_world()


async def _key(c: AsyncClient, scopes: list[str], **extra: Any) -> dict[str, Any]:
    res = await c.post(KEYS, json={"name": "CI server", "scopes": scopes, **extra})
    assert res.status_code == 201, res.text
    body: dict[str, Any] = res.json()
    return body


def _bearer(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


async def test_create_list_and_use_a_key(world: World) -> None:
    async with world.client() as owner, world.client() as script:
        await world.signup_and_verify(owner, "owner@example.com", "Olga")
        job = (await owner.post("/api/jobs/example", json={"steps": 1})).json()
        created = await _key(owner, ["jobs:read", "jobs:write"])
        secret = created["key"]
        assert secret.startswith("pf_") and len(secret) > 40
        assert secret.startswith(created["prefix"]) and len(created["prefix"]) == 11
        assert created["created_by_name"] == "Olga"

        # The secret is never shown again, and never stored.
        listed = (await owner.get(KEYS)).json()["items"]
        assert [k["id"] for k in listed] == [created["id"]]
        assert "key" not in listed[0]
        with sync_session() as s:
            row = s.scalar(select(ApiKey))
            assert row is not None and secret not in (row.key_hash, row.prefix)
            assert row.last_used_at is None

        # A script uses the key (no cookie).
        res = await script.get("/api/jobs", headers=_bearer(secret))
        assert res.status_code == 200, res.text
        assert [j["id"] for j in res.json()["items"]] == [job["id"]]
        assert (
            await script.get(f"/api/jobs/{job['id']}", headers=_bearer(secret))
        ).status_code == 200
        made = await script.post("/api/jobs/example", json={"steps": 1}, headers=_bearer(secret))
        assert made.status_code == 202
        with sync_session() as s:
            row = s.scalar(select(ApiKey))
            assert row is not None and row.last_used_at is not None
        assert world.dispatched[-1].created_by_id is None  # started by a key, not a person


async def test_scopes_limit_what_a_key_can_do(world: World) -> None:
    async with world.client() as owner, world.client() as script:
        await world.signup_and_verify(owner, "owner@example.com")
        read_only = (await _key(owner, ["jobs:read"]))["key"]
        assert (await script.get("/api/jobs", headers=_bearer(read_only))).status_code == 200
        res = await script.post("/api/jobs/example", json={"steps": 1}, headers=_bearer(read_only))
        assert res.status_code == 403
        assert res.json()["error"]["code"] == "permission_denied"


async def test_keys_never_reach_team_or_settings_endpoints(world: World) -> None:
    async with world.client() as owner, world.client() as script:
        await world.signup_and_verify(owner, "owner@example.com")
        key = (await _key(owner, ["jobs:read", "jobs:write"]))["key"]
        for method, path in [
            ("GET", "/api/auth/me"),
            ("GET", "/api/organizations/current/members"),
            ("GET", KEYS),
            ("POST", KEYS),
            ("GET", "/api/organizations/current/audit-log"),
            ("POST", "/api/account/exports"),
        ]:
            res = await script.request(method, path, headers=_bearer(key), json={})
            assert res.status_code == 401, (method, path, res.status_code)


async def test_revoked_expired_and_wrong_keys_fail(world: World) -> None:
    async with world.client() as owner, world.client() as script:
        await world.signup_and_verify(owner, "owner@example.com")
        revoked = await _key(owner, ["jobs:read"])
        assert (await owner.delete(f"{KEYS}/{revoked['id']}")).status_code == 204
        assert (await owner.delete(f"{KEYS}/{revoked['id']}")).status_code == 404
        assert (await owner.get(KEYS)).json()["items"] == []

        expiring = await _key(owner, ["jobs:read"], expires_in_days=30)
        assert expiring["expires_at"] is not None
        assert (await script.get("/api/jobs", headers=_bearer(expiring["key"]))).status_code == 200
        with sync_session() as s:
            s.execute(
                update(ApiKey)
                .where(ApiKey.prefix == expiring["prefix"])
                .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
            )
        assert (await owner.get(KEYS)).json()["items"][0]["expired"] is True

        for bad in [revoked["key"], expiring["key"], "pf_" + "A" * 43, "sk_live_nope", ""]:
            res = await script.get("/api/jobs", headers=_bearer(bad))
            assert res.status_code == 401, bad
        body = (await script.get("/api/jobs", headers=_bearer(revoked["key"]))).json()
        assert body["error"]["code"] == "invalid_api_key"


async def test_key_of_one_workspace_sees_nothing_of_another(world: World) -> None:
    async with world.client() as alice, world.client() as bob, world.client() as script:
        await world.signup_and_verify(alice, "alice@example.com", "Alice")
        await world.signup_and_verify(bob, "bob@example.com", "Bob")
        bobs_job = (await bob.post("/api/jobs/example", json={"steps": 1})).json()
        alice_key = (await _key(alice, ["jobs:read"]))["key"]
        res = await script.get(f"/api/jobs/{bobs_job['id']}", headers=_bearer(alice_key))
        assert res.status_code == 404
        assert (await script.get("/api/jobs", headers=_bearer(alice_key))).json()["items"] == []
        # Bob can't see or revoke Alice's key either.
        alice_key_id = (await alice.get(KEYS)).json()["items"][0]["id"]
        assert (await bob.get(KEYS)).json()["items"] == []
        assert (await bob.delete(f"{KEYS}/{alice_key_id}")).status_code == 404


async def test_requests_per_key_are_limited(world: World) -> None:
    world.settings(api_key_requests_per_minute=2)
    async with world.client() as owner, world.client() as script:
        await world.signup_and_verify(owner, "owner@example.com")
        key = (await _key(owner, ["jobs:read"]))["key"]
        for _ in range(2):
            assert (await script.get("/api/jobs", headers=_bearer(key))).status_code == 200
        res = await script.get("/api/jobs", headers=_bearer(key))
        assert res.status_code == 429
        assert "retry-after" in res.headers


async def test_create_validates_input(world: World) -> None:
    async with world.client() as owner:
        await world.signup_and_verify(owner, "owner@example.com")
        for body in [
            {"name": "x", "scopes": []},
            {"name": "x", "scopes": ["members:manage"]},  # not a key scope
            {"name": "", "scopes": ["jobs:read"]},
            {"name": "x", "scopes": ["jobs:read"], "expires_in_days": 0},
        ]:
            assert (await owner.post(KEYS, json=body)).status_code == 422, body
