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


async def test_redis_rate_limiter_with_real_redis() -> None:
    import uuid

    from redis.asyncio import Redis

    from app.core.rate_limit import RedisRateLimiter

    client = Redis.from_url(get_settings().redis_url)
    limiter = RedisRateLimiter(client)
    key = f"test:{uuid.uuid4()}"
    try:
        assert [await limiter.hit(key, limit=2, window_seconds=30) for _ in range(2)] == [
            None,
            None,
        ]
        wait = await limiter.hit(key, limit=2, window_seconds=30)
        assert wait is not None and 0 < wait <= 30
        assert (await limiter.count(key))[0] == 3
        await limiter.reset(key)
        assert (await limiter.count(key))[0] == 0
    finally:
        await client.aclose()
