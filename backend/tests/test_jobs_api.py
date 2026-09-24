"""Jobs API tests (in-memory store, fake queue)."""

import uuid
from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.config import Environment, Settings
from app.main import create_app
from app.routers.jobs import get_job_service
from app.services.jobs import JobService
from tests.fakes import FakeDispatcher, FakeJobStore


@pytest.fixture
def store() -> FakeJobStore:
    return FakeJobStore()


@pytest.fixture
def dispatcher() -> FakeDispatcher:
    return FakeDispatcher()


@pytest.fixture
async def jobs_client(
    app: FastAPI, store: FakeJobStore, dispatcher: FakeDispatcher
) -> AsyncIterator[AsyncClient]:
    app.dependency_overrides[get_job_service] = lambda: JobService(store, dispatcher)
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


async def test_jobs_api_is_off_in_production_until_auth_exists() -> None:
    prod = Settings(_env_file=None, environment=Environment.PRODUCTION, secret_key="x" * 40)
    assert prod.jobs_api_enabled is False
    transport = ASGITransport(app=create_app(prod), raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        assert (await c.get("/api/jobs")).status_code == 404


def test_jobs_api_can_be_forced_on_or_off() -> None:
    assert Settings(_env_file=None, jobs_api_enabled=False).jobs_api_enabled is False
    assert Settings(_env_file=None, environment=Environment.TEST).jobs_api_enabled is True
