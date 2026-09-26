"""Jobs API tests (in-memory store, fake queue)."""

import uuid
from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.models.organization import Membership, Organization, Role
from app.models.session import UserSession
from app.models.user import User
from app.routers.deps import get_org_context
from app.routers.jobs import get_job_service
from app.services.jobs import JobService
from app.services.organizations import OrgContext
from tests.fakes import FakeDispatcher, FakeJobStore


@pytest.fixture
def store() -> FakeJobStore:
    return FakeJobStore()


@pytest.fixture
def dispatcher() -> FakeDispatcher:
    return FakeDispatcher()


ORG_ID = uuid.uuid4()


def fake_context() -> OrgContext:
    """A signed-in user in one workspace (the real sign-in is tested in test_auth_flows)."""
    user = User(id=uuid.uuid4(), email="a@example.com", name="A")
    org = Organization(id=ORG_ID, name="A's workspace")
    return OrgContext(
        user=user,
        session=UserSession(user_id=user.id),
        organization=org,
        membership=Membership(organization_id=org.id, user_id=user.id, role=Role.OWNER),
    )


@pytest.fixture
async def jobs_client(
    app: FastAPI, store: FakeJobStore, dispatcher: FakeDispatcher
) -> AsyncIterator[AsyncClient]:
    app.dependency_overrides[get_job_service] = lambda: JobService(store, dispatcher)
    app.dependency_overrides[get_org_context] = fake_context
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_create_example_job_returns_202_and_queued_job(
    jobs_client: AsyncClient, dispatcher: FakeDispatcher
) -> None:
    res = await jobs_client.post("/api/jobs/example", json={"steps": 3})
    assert res.status_code == 202, res.text
    body = res.json()
    assert body["status"] == "queued"
    assert body["progress"] == 0
    assert body["kind"] == "example"
    assert str(dispatcher.sent[0].id) == body["id"]


async def test_create_example_job_validates_input(jobs_client: AsyncClient) -> None:
    too_many = await jobs_client.post("/api/jobs/example", json={"steps": 500})
    unknown_field = await jobs_client.post("/api/jobs/example", json={"steps": 2, "sql": "x"})
    assert too_many.status_code == 422
    assert too_many.json()["error"]["code"] == "validation_error"
    assert unknown_field.status_code == 422


async def test_queue_down_returns_503_in_standard_format(app: FastAPI, store: FakeJobStore) -> None:
    app.dependency_overrides[get_job_service] = lambda: JobService(store, FakeDispatcher(fail=True))
    app.dependency_overrides[get_org_context] = fake_context
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        res = await c.post("/api/jobs/example", json={})
    assert res.status_code == 503
    assert res.json()["error"]["code"] == "service_unavailable"
    assert "secret" not in res.text


async def test_get_and_list_jobs(jobs_client: AsyncClient) -> None:
    created = (await jobs_client.post("/api/jobs/example", json={"steps": 1})).json()
    one = await jobs_client.get(f"/api/jobs/{created['id']}")
    listed = await jobs_client.get("/api/jobs", params={"limit": 5})
    assert one.status_code == 200
    assert one.json()["id"] == created["id"]
    assert [j["id"] for j in listed.json()["items"]] == [created["id"]]


async def test_get_unknown_job_is_404(jobs_client: AsyncClient) -> None:
    res = await jobs_client.get(f"/api/jobs/{uuid.uuid4()}")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "not_found"


async def test_get_job_with_bad_id_is_422(jobs_client: AsyncClient) -> None:
    res = await jobs_client.get("/api/jobs/not-a-uuid")
    assert res.status_code == 422


async def test_list_limit_is_bounded(jobs_client: AsyncClient) -> None:
    res = await jobs_client.get("/api/jobs", params={"limit": 1000})
    assert res.status_code == 422


async def test_jobs_need_sign_in(app: FastAPI) -> None:
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        res = await c.get("/api/jobs")
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "unauthorized"


async def test_created_job_belongs_to_active_workspace(
    jobs_client: AsyncClient, dispatcher: FakeDispatcher
) -> None:
    await jobs_client.post("/api/jobs/example", json={"steps": 1})
    assert dispatcher.sent[0].organization_id == ORG_ID
