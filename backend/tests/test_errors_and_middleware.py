"""Error envelope, request id and logging tests."""

from fastapi import FastAPI, Query
from httpx import ASGITransport, AsyncClient

from app.core.errors import NotFoundError
from app.core.logging import redact_secrets


def _add_test_routes(app: FastAPI) -> None:
    @app.get("/api/test/not-found")
    async def not_found() -> None:
        raise NotFoundError("Project not found.")

    @app.get("/api/test/boom")
    async def boom() -> None:
        raise RuntimeError("database password=secret123 leaked?")

    @app.get("/api/test/validate")
    async def validate(limit: int = Query(ge=1, le=10)) -> dict[str, int]:
        return {"limit": limit}


async def _client(app: FastAPI) -> AsyncClient:
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    return AsyncClient(transport=transport, base_url="http://test")


async def test_app_error_uses_standard_envelope(app: FastAPI) -> None:
    _add_test_routes(app)
    async with await _client(app) as c:
        res = await c.get("/api/test/not-found")
    assert res.status_code == 404
    err = res.json()["error"]
    assert err["code"] == "not_found"
    assert err["message"] == "Project not found."
    assert err["request_id"] == res.headers["X-Request-ID"]


async def test_unknown_route_uses_standard_envelope(app: FastAPI) -> None:
    async with await _client(app) as c:
        res = await c.get("/api/does-not-exist")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "not_found"


async def test_validation_error_has_field_details(app: FastAPI) -> None:
    _add_test_routes(app)
    async with await _client(app) as c:
        res = await c.get("/api/test/validate", params={"limit": 99})
    assert res.status_code == 422
    err = res.json()["error"]
    assert err["code"] == "validation_error"
    assert err["details"][0]["field"] == "query.limit"


async def test_unhandled_error_is_generic_and_has_request_id(app: FastAPI) -> None:
    _add_test_routes(app)
    async with await _client(app) as c:
        res = await c.get("/api/test/boom")
    assert res.status_code == 500
    err = res.json()["error"]
    assert err["code"] == "internal_error"
    assert "secret123" not in res.text
    assert err["request_id"]
    assert res.headers["X-Request-ID"] == err["request_id"]


async def test_request_id_is_generated(client: AsyncClient) -> None:
    res = await client.get("/api/health")
    assert len(res.headers["X-Request-ID"]) == 32


async def test_valid_incoming_request_id_is_kept(client: AsyncClient) -> None:
    res = await client.get("/api/health", headers={"X-Request-ID": "caddy-abc-12345"})
    assert res.headers["X-Request-ID"] == "caddy-abc-12345"


async def test_malformed_incoming_request_id_is_replaced(client: AsyncClient) -> None:
    res = await client.get("/api/health", headers={"X-Request-ID": "<script>alert(1)</script>"})
    assert res.headers["X-Request-ID"] != "<script>alert(1)</script>"


def test_redact_secrets_hides_sensitive_keys() -> None:
    event = {"event": "login", "password": "p", "Authorization": "Bearer x", "user": "ezat"}
    out = redact_secrets(None, "info", event)
    assert out["password"] == "[REDACTED]"
    assert out["Authorization"] == "[REDACTED]"
    assert out["user"] == "ezat"


async def test_cors_allows_configured_origin_only(client: AsyncClient) -> None:
    ok = await client.options(
        "/api/health",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"},
    )
    bad = await client.options(
        "/api/health",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:3000"
    assert "access-control-allow-origin" not in bad.headers


async def test_docs_hidden_in_production() -> None:
    from app.core.config import Environment, Settings
    from app.main import create_app

    prod = Settings(_env_file=None, environment=Environment.PRODUCTION, secret_key="x" * 40)
    async with await _client(create_app(prod)) as c:
        assert (await c.get("/api/docs")).status_code == 404
        assert (await c.get("/api/openapi.json")).status_code == 404
