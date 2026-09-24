"""Shared test fixtures. Unit tests need no real Postgres or Redis."""

import os
from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("ENVIRONMENT", "test")

from app.core.config import Environment, Settings
from app.main import create_app
from app.routers.health import get_health_service
from app.services.health import Checker, HealthService


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
