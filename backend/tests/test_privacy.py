"""GDPR: data exports (ZIP), scheduled deletion of accounts and workspaces, nightly purge."""

import io
import json
import zipfile
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, update

from app.db.session import sync_session
from app.models.audit_log import AuditLog
from app.models.data_export import DataExport
from app.models.organization import Organization
from app.models.user import User
from app.services.purge import cleanup, purge_due
from tests.helpers import World, build_world

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_db")]


@pytest.fixture
def world() -> World:
    return build_world()


def _zip(content: bytes) -> dict[str, Any]:
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        return {
            name: (z.read(name).decode() if name.endswith(".txt") else json.loads(z.read(name)))
            for name in z.namelist()
        }


async def _export(world: World, c: AsyncClient, path: str) -> dict[str, Any]:
    res = await c.post(path)
    assert res.status_code == 202, res.text
    export: dict[str, Any] = res.json()
    assert export["ready"] is False and export["job_id"]
    await world.run_jobs()  # the real worker code, in-process
    job = (await c.get(f"/api/jobs/{export['job_id']}")).json()
    assert job["status"] == "done", job
    assert "Your export is ready" in job["message"]
    return export


# --- exports -----------------------------------------------------------------------------


async def test_account_export_contains_my_data_and_no_secrets(world: World) -> None:
    async with world.client() as me_c:
        me = await world.signup_and_verify(me_c, "ezat@example.com", "Ezat Hotak")
        await me_c.post("/api/jobs/example", json={"steps": 1})
        export = await _export(world, me_c, "/api/account/exports")

        listed = (await me_c.get("/api/exports")).json()["items"]
        assert [e["id"] for e in listed] == [export["id"]] and listed[0]["ready"] is True

        res = await me_c.get(export["download_url"])
        assert res.status_code == 200
        assert res.headers["content-type"] == "application/zip"
        assert "attachment" in res.headers["content-disposition"]
        files = _zip(res.content)
        assert set(files) == {
            "README.txt",
            "profile.json",
            "workspaces.json",
            "sign_ins.json",
            "activity.json",
            "jobs.json",
        }
        assert files["profile.json"]["email"] == "ezat@example.com"
        assert files["profile.json"]["sign_in_with_password"] is True
        assert files["workspaces.json"][0]["workspace_id"] == me["active_organization_id"]
        assert any(a["action"] == "auth.login" for a in files["activity.json"])
        assert [j["kind"] for j in files["jobs.json"]] == ["example", "data_export"]
        blob = res.content.decode("latin-1") + json.dumps(files)
        for secret_field in ("password_hash", "token_hash", "key_hash", "argon2"):
            assert secret_field not in blob


async def test_exports_are_private(world: World) -> None:
    async with world.client() as owner, world.client() as m:
        await world.signup_and_verify(owner, "owner@example.com", "Owner")
        await world.invite_and_join(owner, m, "m@example.com", role="admin")
        export = await _export(world, owner, "/api/account/exports")
        # A colleague (even an admin) can't see the job or download my export.
        assert (await m.get(f"/api/jobs/{export['job_id']}")).status_code == 404
        assert all(j["kind"] != "data_export" for j in (await m.get("/api/jobs")).json()["items"])
        assert (await m.get(export["download_url"])).status_code == 404
        assert (await m.get("/api/exports")).json()["items"] == []


async def test_workspace_export_for_admins(world: World) -> None:
    async with world.client() as owner, world.client() as admin, world.client() as m:
        await world.signup_and_verify(owner, "owner@example.com", "Owner")
        await world.invite_and_join(owner, admin, "admin@example.com", role="admin")
        await world.invite_and_join(owner, m, "m@example.com")
        export = await _export(world, admin, "/api/organizations/current/exports")
        assert export["filename"].startswith("owner-s-workspace-export-")
        files = _zip((await owner.get(export["download_url"])).content)  # owner may too
        assert {
            "workspace.json",
            "members.json",
            "invites.json",
            "api_keys.json",
            "audit_log.json",
            "jobs.json",
        } <= set(files)
        assert sorted(x["email"] for x in files["members.json"]) == [
            "admin@example.com",
            "m@example.com",
            "owner@example.com",
        ]
        assert any(e["action"] == "org.exported" for e in files["audit_log.json"])
        # Members can't start or download workspace exports.
        assert (await m.post("/api/organizations/current/exports")).status_code == 403
        assert (await m.get(export["download_url"])).status_code == 404


async def test_export_not_ready_expired_and_rate_limited(world: World) -> None:
    async with world.client() as c:
        await world.signup_and_verify(c, "a@example.com")
        export = (await c.post("/api/account/exports")).json()
        res = await c.get(export["download_url"])
        assert res.status_code == 409
        assert res.json()["error"]["code"] == "export_not_ready"
        for _ in range(4):
            assert (await c.post("/api/account/exports")).status_code == 202
        assert (await c.post("/api/account/exports")).status_code == 429

        await world.run_jobs()
        with sync_session() as s:
            s.execute(
                update(DataExport).values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
            )
        assert (await c.get(export["download_url"])).status_code == 404
        assert (await c.get("/api/exports")).json()["items"] == []


# --- scheduled deletion ------------------------------------------------------------------


async def test_schedule_and_cancel_account_deletion(world: World) -> None:
    async with world.client() as c:
        await world.signup_and_verify(c, "del@example.com", "Dora")
        wrong = await c.post("/api/account/deletion", json={"confirm": "someone@example.com"})
        assert wrong.status_code == 400
        assert wrong.json()["error"]["code"] == "confirmation_mismatch"

        res = await c.post("/api/account/deletion", json={"confirm": "DEL@example.com"})
        assert res.status_code == 200
        when = datetime.fromisoformat(res.json()["deletion_scheduled_at"])
        assert timedelta(days=13) < when - datetime.now(UTC) <= timedelta(days=14)
        mail = world.email.last_to("del@example.com")
        assert "will be deleted" in mail.subject
        me = (await c.get("/api/auth/me")).json()
        assert me["user"]["deletion_scheduled_at"] is not None

        res = await c.delete("/api/account/deletion")
        assert res.json() == {"deletion_scheduled_at": None}
        assert (await c.get("/api/auth/me")).json()["user"]["deletion_scheduled_at"] is None


async def test_owner_of_a_shared_workspace_must_transfer_first(world: World) -> None:
    async with world.client() as owner, world.client() as m:
        await world.signup_and_verify(owner, "owner@example.com", "Owner")
        await world.invite_and_join(owner, m, "m@example.com")
        res = await owner.post("/api/account/deletion", json={"confirm": "owner@example.com"})
        assert res.status_code == 409
        assert res.json()["error"]["details"]["workspaces"][0]["name"] == "Owner's workspace"
        # The member owns no shared workspace, so they may delete their account.
        assert (
            await m.post("/api/account/deletion", json={"confirm": "m@example.com"})
        ).status_code == 200


async def test_schedule_and_cancel_workspace_deletion(world: World) -> None:
    async with world.client() as owner, world.client() as admin:
        await world.signup_and_verify(owner, "owner@example.com", "Owner")
        await world.invite_and_join(owner, admin, "a@example.com", role="admin")
        path = "/api/organizations/current/deletion"
        assert (await admin.post(path, json={"confirm": "Owner's workspace"})).status_code == 403
        assert (await owner.post(path, json={"confirm": "owner's workspace"})).status_code == 400
        res = await owner.post(path, json={"confirm": "Owner's workspace"})
        assert res.status_code == 200
        assert res.json()["deletion_scheduled_at"] is not None
        # Everyone in the workspace sees it (the app shows a banner).
        org = (await admin.get("/api/auth/me")).json()["organizations"][0]
        assert org["deletion_scheduled_at"] is not None
        assert "will be deleted" in world.email.last_to("owner@example.com").subject
        assert (await admin.delete(path)).status_code == 403
        assert (await owner.delete(path)).json() == {"deletion_scheduled_at": None}


# --- nightly purge -----------------------------------------------------------------------


def _due(model: type[User] | type[Organization]) -> None:
    """Move every scheduled deletion into the past."""
    with sync_session() as s:
        s.execute(
            update(model)
            .where(model.deletion_scheduled_at.is_not(None))
            .values(deletion_scheduled_at=datetime.now(UTC) - timedelta(minutes=1))
        )


def _count(model: type[Any], *where: Any) -> int:
    with sync_session() as s:
        return int(s.scalar(select(func.count()).select_from(model).where(*where)) or 0)


async def test_purge_deletes_the_account_and_its_personal_workspace(world: World) -> None:
    async with world.client() as owner, world.client() as m:
        await world.signup_and_verify(owner, "owner@example.com", "Owner")
        # m joins the owner's team, and also has a personal workspace of their own.
        await world.invite_and_join(owner, m, "m@example.com", name="Max")
        await m.post("/api/organizations", json={"name": "Max private"})
        await m.post("/api/account/deletion", json={"confirm": "m@example.com"})

        # Not due yet: nothing happens.
        assert purge_due(sync_session, datetime.now(UTC)) == {"users": 0, "workspaces": 0}
        _due(User)
        assert purge_due(sync_session, datetime.now(UTC)) == {"users": 1, "workspaces": 0}

        assert _count(User, User.email == "m@example.com") == 0
        assert _count(Organization, Organization.name == "Max private") == 0
        # The team workspace stays; Max's past actions there show as "deleted user".
        assert _count(Organization, Organization.name == "Owner's workspace") == 1
        log = (await owner.get("/api/organizations/current/audit-log")).json()["items"]
        joined = next(e for e in log if e["action"] == "member.joined")
        assert joined["actor"] == {"type": "deleted_user", "name": None, "email": None}
        # Max's personal account events (sign-ins) are gone.
        assert (
            _count(AuditLog, AuditLog.organization_id.is_(None), AuditLog.actor_user_id.is_(None))
            == 0
        )
        assert (await m.get("/api/auth/me")).status_code == 401


async def test_purge_hands_ownership_to_an_admin(world: World) -> None:
    async with world.client() as owner, world.client() as admin, world.client() as m:
        await world.signup_and_verify(owner, "owner@example.com", "Owner")
        # Scheduled while alone in the workspace ...
        await owner.post("/api/account/deletion", json={"confirm": "owner@example.com"})
        # ... then people joined.
        await world.invite_and_join(owner, m, "m@example.com")
        await world.invite_and_join(owner, admin, "admin@example.com", role="admin")
        _due(User)
        assert purge_due(sync_session, datetime.now(UTC))["users"] == 1
        me = (await admin.get("/api/auth/me")).json()
        assert me["organizations"][0]["role"] == "owner"
        log = (await admin.get("/api/organizations/current/audit-log")).json()["items"]
        assert log[0]["action"] == "org.ownership_transferred"
        assert log[0]["actor"]["type"] == "system"


async def test_purge_deletes_a_workspace_but_not_its_people(world: World) -> None:
    async with world.client() as owner, world.client() as m:
        me = await world.signup_and_verify(owner, "owner@example.com", "Owner")
        await world.invite_and_join(owner, m, "m@example.com")
        await owner.post("/api/jobs/example", json={"steps": 1})
        await owner.post(
            "/api/organizations/current/deletion", json={"confirm": "Owner's workspace"}
        )
        _due(Organization)
        assert purge_due(sync_session, datetime.now(UTC)) == {"users": 0, "workspaces": 1}
        assert _count(Organization, Organization.id == me["active_organization_id"]) == 0
        assert _count(User) == 2
        # Both can still sign in; each gets a fresh workspace.
        assert (await owner.get("/api/auth/me")).status_code == 200
        assert (await m.get("/api/auth/me")).json()["organizations"][0]["role"] == "owner"


async def test_cancelled_deletion_is_not_purged(world: World) -> None:
    async with world.client() as c:
        await world.signup_and_verify(c, "a@example.com")
        await c.post("/api/account/deletion", json={"confirm": "a@example.com"})
        _due(User)
        await c.delete("/api/account/deletion")
        assert purge_due(sync_session, datetime.now(UTC))["users"] == 0
        assert _count(User) == 1


async def test_cleanup_removes_expired_exports_and_old_audit(world: World) -> None:
    async with world.client() as c:
        await world.signup_and_verify(c, "a@example.com")
        await c.post("/api/account/exports")
        await world.run_jobs()
        with sync_session() as s:
            s.execute(update(DataExport).values(expires_at=datetime.now(UTC) - timedelta(days=1)))
            s.execute(
                update(AuditLog)
                .where(AuditLog.action == "org.created")
                .values(created_at=datetime.now(UTC) - timedelta(days=400))
            )
        counts = cleanup(sync_session, datetime.now(UTC), audit_retention_days=365)
        assert counts == {"exports": 1, "audit_events": 1}
        assert _count(DataExport) == 0
