"""Integration tests against real Postgres + Redis.

Skipped unless RUN_INTEGRATION=1 (set by `make test`, which runs inside Docker, and by CI).
"""

import os

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import get_async_engine
from app.main import create_app

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("RUN_INTEGRATION") != "1", reason="set RUN_INTEGRATION=1"),
]


async def test_readiness_with_real_services() -> None:
    app = create_app(get_settings())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        res = await c.get("/api/health/ready")
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "ok"
    await get_async_engine().dispose()


async def test_migrations_applied_and_pgvector_enabled() -> None:
    async with get_async_engine().connect() as conn:
        revision = (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar()
        vector = (
            await conn.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'"))
        ).scalar()
    assert revision is not None
    assert vector == 1
    await get_async_engine().dispose()
