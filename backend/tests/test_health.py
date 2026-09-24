"""Health endpoint tests."""

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app import __version__
from app.core.config import Settings


async def test_liveness_returns_ok(client: AsyncClient) -> None:
    res = await client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok", "version": __version__, "environment": "test"}


async def test_readiness_ok_when_all_dependencies_up(client: AsyncClient) -> None:
    res = await client.get("/api/health/ready")
    body = res.json()
    assert res.status_code == 200
    assert body["status"] == "ok"
    assert {c["name"] for c in body["checks"]} == {"database", "redis"}
    assert all(c["latency_ms"] is not None for c in body["checks"])


async def test_readiness_503_and_no_secret_leak_when_db_down(db_down_app: FastAPI) -> None:
    transport = ASGITransport(app=db_down_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        res = await c.get("/api/health/ready")
    assert res.status_code == 503
    body = res.json()
    db = next(c for c in body["checks"] if c["name"] == "database")
    assert db["status"] == "error"
    assert db["error"] == "ConnectionError"
    # The raw exception text (host, password) must never reach the client.
    assert "hunter2" not in res.text
    assert "10.0.0.5" not in res.text


async def test_readiness_reports_timeout(app: FastAPI, settings: Settings) -> None:
    import asyncio

    from tests.conftest import use_checkers

    async def slow() -> None:
        await asyncio.sleep(5)

    settings.health_check_timeout = 0.05
    use_checkers(app, settings, {"database": slow})
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        res = await c.get("/api/health/ready")
    assert res.status_code == 503
    assert res.json()["checks"][0]["error"] == "timeout"
