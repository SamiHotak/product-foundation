"""The app admin area: only superusers, numbers across workspaces, failed jobs + retry,
the AI kill switch, and viewing the app as a user (impersonation) with audit."""

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update

from app.core.config import get_settings
from app.db.session import sync_session
from app.models.audit_log import AuditLog
from app.models.job import Job, JobStatus
from app.models.llm_call import LlmCall
from app.models.user import User
from app.scripts import make_admin
from tests.helpers import World, build_world, set_plan

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_db")]


@pytest.fixture
def world() -> World:
    return build_world()


def _make_admin(email: str, admin: bool = True) -> None:
    with sync_session() as s:
        s.execute(update(User).where(User.email == email).values(is_superuser=admin))


async def _setup(world: World, admin: AsyncClient, customer: AsyncClient) -> dict[str, Any]:
    await world.signup_and_verify(admin, "admin@example.com", "Ada Admin")
    me = await world.signup_and_verify(customer, "customer@example.com", "Carl Customer")
    _make_admin("admin@example.com")
    return me


async def test_only_app_admins_get_in(world: World) -> None:
    async with world.client() as c, world.client() as anon:
        me = await world.signup_and_verify(c, "owner@example.com")
        assert me["user"]["is_superuser"] is False
        for path in ["/api/admin/overview", "/api/admin/users", "/api/admin/organizations"]:
            assert (await c.get(path)).status_code == 403
            assert (await anon.get(path)).status_code == 401
        make_admin.main(["owner@example.com"])
        assert (await c.get("/api/admin/overview")).status_code == 200
        assert (await c.get("/api/auth/me")).json()["user"]["is_superuser"] is True
        make_admin.main(["owner@example.com", "--remove"])
        assert (await c.get("/api/admin/overview")).status_code == 403
        with pytest.raises(SystemExit):
            make_admin.main(["nobody@example.com"])


async def test_lists_and_numbers(world: World) -> None:
    async with world.client() as admin, world.client() as customer:
        me = await _setup(world, admin, customer)
        org = me["active_organization_id"]
        set_plan(org, "pro")
        await customer.post("/api/jobs/example", json={"steps": 1})
        with sync_session() as s:
            s.add(
                LlmCall(
                    organization_id=uuid.UUID(org),
                    task="summarize",
                    provider="openai",
                    model="gpt-6-luna",
                    status="ok",
                    input_tokens=1000,
                    output_tokens=100,
                    cost_micro_usd=150_000,
                    latency_ms=900,
                    attempts=1,
                    trace_id="a" * 32,
                )
            )
        overview = (await admin.get("/api/admin/overview")).json()
        assert overview["users"] == 2 and overview["workspaces"] == 2
        assert overview["paid_workspaces"] == 1
        assert overview["ai_requests_month"] == 1 and overview["ai_cost_usd_month"] == 0.15
        assert overview["ai_paused"] is False and overview["ai_provider"] == "openai"

        orgs = (await admin.get("/api/admin/organizations", params={"search": "carl"})).json()
        [row] = orgs["items"]
        assert row["owner_email"] == "customer@example.com" and row["plan_id"] == "pro"
        assert row["members"] == 1 and row["ai_requests_month"] == 1
        # Search is plain text, never a pattern.
        assert (await admin.get("/api/admin/organizations", params={"search": "%"})).json() == {
            "items": []
        }

        users = (await admin.get("/api/admin/users", params={"search": "ada"})).json()["items"]
        assert [u["email"] for u in users] == ["admin@example.com"]
        assert users[0]["is_superuser"] is True and users[0]["workspaces"] == 1

        subs = (await admin.get("/api/admin/subscriptions")).json()["items"]
        assert [s["plan_id"] for s in subs] == ["pro"]

        usage = (await admin.get("/api/admin/usage")).json()
        assert usage["total_requests"] == 1 and usage["rows"][0]["cost_usd"] == 0.15
        last_year = (await admin.get("/api/admin/usage", params={"month": "2020-05-17"})).json()
        assert last_year["month"] == "2020-05-01" and last_year["rows"] == []


async def test_failed_jobs_can_be_retried(world: World) -> None:
    async with world.client() as admin, world.client() as customer:
        await _setup(world, admin, customer)
        job = (await customer.post("/api/jobs/example", json={"steps": 2, "fail": True})).json()
        await world.run_jobs()
        failed = (await admin.get("/api/admin/jobs/failed")).json()["items"]
        assert [j["id"] for j in failed] == [job["id"]]
        assert failed[0]["started_by"] == "customer@example.com"
        assert "asked it to fail" in failed[0]["error"]

        res = await admin.post(f"/api/admin/jobs/{job['id']}/retry")
        assert res.status_code == 204
        assert [str(j.id) for j in world.dispatched] == [job["id"]]
        with sync_session() as s:
            row = s.get(Job, uuid.UUID(job["id"]))
            assert row is not None and row.status is JobStatus.QUEUED and row.error is None
        assert (await admin.post(f"/api/admin/jobs/{job['id']}/retry")).status_code == 409
        assert (await admin.post(f"/api/admin/jobs/{uuid.uuid4()}/retry")).status_code == 404
        # The customer's workspace sees that an admin retried it.
        with sync_session() as s:
            actions = list(s.scalars(select(AuditLog.action)))
        assert "admin.job_retried" in actions


async def test_ai_kill_switch(world: World) -> None:
    async with world.client() as admin, world.client() as customer:
        await _setup(world, admin, customer)
        res = await admin.put("/api/admin/ai", json={"paused": True})
        assert res.status_code == 200 and res.json()["ai_paused"] is True
        status = (await customer.get("/api/ai/status")).json()
        assert status["available"] is False
        res = await customer.post("/api/ai/summaries", json={"text": "A text that is long enough."})
        assert res.status_code == 503
        await admin.put("/api/admin/ai", json={"paused": False})
        assert (await customer.get("/api/ai/status")).json()["available"] is True
        assert (await customer.put("/api/admin/ai", json={"paused": True})).status_code == 403


async def test_view_the_app_as_a_customer(world: World) -> None:
    async with world.client() as admin, world.client() as customer:
        me = await _setup(world, admin, customer)
        customer_id = me["user"]["id"]
        own_cookie = admin.cookies.get(get_settings().session_cookie_name)

        res = await admin.post(f"/api/admin/users/{customer_id}/impersonate")
        assert res.status_code == 204
        viewed = (await admin.get("/api/auth/me")).json()
        assert viewed["user"]["email"] == "customer@example.com"
        assert viewed["impersonator"]["email"] == "admin@example.com"
        assert viewed["active_organization_id"] == me["active_organization_id"]

        # Reading and trying things out is possible; the customer's audit log shows support looked.
        assert (await admin.post("/api/jobs/example", json={"steps": 1})).status_code == 202
        assert (await admin.get("/api/organizations/current/members")).status_code == 200
        with sync_session() as s:
            started = s.scalar(
                select(AuditLog).where(
                    AuditLog.action == "admin.impersonation_started",
                    AuditLog.organization_id == uuid.UUID(me["active_organization_id"]),
                )
            )
            assert started is not None

        # Changes only the user may make are blocked: support access can't outlive the view
        # (e.g. by inviting yourself), and nothing is changed in the customer's name.
        res = await admin.patch("/api/organizations/current", json={"name": "Renamed by support"})
        assert res.status_code == 403
        res = await admin.post(
            "/api/organizations/current/invites",
            json={"email": "me-later@example.com", "role": "admin"},
        )
        assert res.status_code == 403
        assert res.json()["error"]["code"] == "not_while_impersonating"

        # Account and money actions are blocked, and so is /admin itself.
        res = await admin.put(
            "/api/account/password", json={"current_password": "x", "new_password": "y" * 12}
        )
        assert res.status_code == 403
        assert res.json()["error"]["code"] == "not_while_impersonating"
        assert (
            await admin.post("/api/billing/checkout", json={"plan_id": "pro"})
        ).status_code == 403
        assert (await admin.get("/api/admin/overview")).status_code == 403

        # Stop: back to the admin's own session.
        res = await admin.post("/api/admin/impersonation/stop")
        assert res.status_code == 200 and res.json() == {"restored_admin_session": True}
        assert admin.cookies.get(get_settings().session_cookie_name) == own_cookie
        back = (await admin.get("/api/auth/me")).json()
        assert back["user"]["email"] == "admin@example.com" and back["impersonator"] is None
        assert (await admin.post("/api/admin/impersonation/stop")).status_code == 409
        with sync_session() as s:
            assert s.scalar(select(AuditLog).where(AuditLog.action == "admin.impersonation_ended"))


async def test_impersonation_rules(world: World) -> None:
    async with world.client() as admin, world.client() as customer, world.client() as other:
        me = await _setup(world, admin, customer)
        admin_me = (await admin.get("/api/auth/me")).json()
        await world.signup_and_verify(other, "second-admin@example.com")
        _make_admin("second-admin@example.com")
        second = (await other.get("/api/auth/me")).json()["user"]["id"]
        assert (
            await admin.post(f"/api/admin/users/{admin_me['user']['id']}/impersonate")
        ).status_code == 409
        assert (await admin.post(f"/api/admin/users/{second}/impersonate")).status_code == 403
        assert (await admin.post(f"/api/admin/users/{uuid.uuid4()}/impersonate")).status_code == 404
        # The view ends at once when the admin loses admin rights.
        assert (
            await admin.post(f"/api/admin/users/{me['user']['id']}/impersonate")
        ).status_code == 204
        _make_admin("admin@example.com", admin=False)
        assert (await admin.get("/api/auth/me")).status_code == 401
