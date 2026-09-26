"""Shared test fixtures.

- Unit tests need no Postgres or Redis.
- Integration tests (RUN_INTEGRATION=1, set by `make test` and CI) use a SEPARATE database,
  `<name>_test`, so running the tests never touches your development data.
"""

import os
from collections.abc import AsyncIterator, Iterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("ENVIRONMENT", "test")
RUN_INTEGRATION = os.getenv("RUN_INTEGRATION") == "1"
if RUN_INTEGRATION:
    _url = os.environ.get("DATABASE_URL", "postgresql+psycopg://app:app@localhost:5432/app")
    if not _url.endswith("_test"):
        os.environ["DATABASE_URL"] = _url + "_test"

from app.core.config import Environment, Settings  # noqa: E402 - env must be set first
from app.main import create_app  # noqa: E402 - env must be set first
from app.routers.health import get_health_service  # noqa: E402 - env must be set first
from app.services.health import Checker, HealthService  # noqa: E402 - env must be set first


async def _ok() -> None:
    return None


async def _down() -> None:
    raise ConnectionError("connection refused to 10.0.0.5:5432 password=hunter2")


@pytest.fixture
def settings() -> Settings:
    """Settings for tests (no .env file)."""
    return Settings(_env_file=None, environment=Environment.TEST, log_format="json")


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    """A fresh app per test."""
    return create_app(settings)


def use_checkers(app: FastAPI, settings: Settings, checkers: dict[str, Checker]) -> None:
    """Replace the real health checkers with fakes."""
    app.dependency_overrides[get_health_service] = lambda: HealthService(settings, checkers)


@pytest.fixture
def healthy_app(app: FastAPI, settings: Settings) -> FastAPI:
    """App whose dependencies all look healthy."""
    use_checkers(app, settings, {"database": _ok, "redis": _ok})
    return app


@pytest.fixture
def db_down_app(app: FastAPI, settings: Settings) -> FastAPI:
    """App whose database check fails."""
    use_checkers(app, settings, {"database": _down, "redis": _ok})
    return app


@pytest.fixture
async def client(healthy_app: FastAPI) -> AsyncIterator[AsyncClient]:
    """HTTP client for the healthy app."""
    transport = ASGITransport(app=healthy_app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# --- integration database ------------------------------------------------------------------


def _ensure_test_database() -> None:
    """Create `<name>_test` if missing and migrate it to the latest version."""
    import psycopg
    from alembic.config import Config
    from sqlalchemy.engine import make_url

    from alembic import command

    url = make_url(os.environ["DATABASE_URL"])
    admin = url.set(drivername="postgresql", database="postgres").render_as_string(
        hide_password=False
    )
    with psycopg.connect(admin, autocommit=True) as conn:
        exists = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (url.database,)
        ).fetchone()
        if not exists:
            conn.execute(f'CREATE DATABASE "{url.database}"')
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    command.upgrade(Config(os.path.join(here, "alembic.ini")), "head")


@pytest.fixture(scope="session")
def migrated_db() -> Iterator[None]:
    """Once per test run: a migrated test database."""
    if not RUN_INTEGRATION:
        pytest.skip("set RUN_INTEGRATION=1")
    _ensure_test_database()
    yield


@pytest.fixture
async def clean_db(migrated_db: None) -> AsyncIterator[None]:
    """Empty tables before each integration test; close pooled connections after."""
    from sqlalchemy import text

    from app.db.session import get_async_engine
    from app.models import Base

    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    async with get_async_engine().begin() as conn:
        await conn.execute(text(f"TRUNCATE {tables} CASCADE"))
    yield
    await get_async_engine().dispose()
