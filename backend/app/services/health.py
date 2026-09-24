"""Health checks for the database and Redis.

Each checker is a small async callable, so tests can swap in fakes.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable

from redis.asyncio import Redis
from sqlalchemy import text

from app import __version__
from app.core.config import Settings
from app.core.logging import get_logger
from app.db.session import get_async_engine
from app.schemas.health import DependencyCheck, LivenessResponse, ReadinessResponse

logger = get_logger(__name__)

Checker = Callable[[], Awaitable[None]]


async def check_database() -> None:
    """Run `SELECT 1` against Postgres."""
    async with get_async_engine().connect() as conn:
        await conn.execute(text("SELECT 1"))


def make_redis_checker(redis_url: str) -> Checker:
    """Return a checker that PINGs Redis."""

    async def check_redis() -> None:
        client = Redis.from_url(redis_url)
        try:
            await client.ping()
        finally:
            await client.aclose()

    return check_redis


class HealthService:
    """Builds liveness and readiness reports."""

    def __init__(self, settings: Settings, checkers: dict[str, Checker]) -> None:
        self._settings = settings
        self._checkers = checkers

    def liveness(self) -> LivenessResponse:
        """Cheap check: the process answers."""
        return LivenessResponse(version=__version__, environment=self._settings.environment.value)

    async def readiness(self) -> ReadinessResponse:
        """Run all dependency checks in parallel, each with a timeout."""
        results = await asyncio.gather(
            *(self._run(name, checker) for name, checker in self._checkers.items())
        )
        overall = "ok" if all(r.status == "ok" for r in results) else "error"
        return ReadinessResponse(
            status=overall,
            version=__version__,
            environment=self._settings.environment.value,
            checks=list(results),
        )

    async def _run(self, name: str, checker: Checker) -> DependencyCheck:
        start = time.perf_counter()
        try:
            await asyncio.wait_for(checker(), timeout=self._settings.health_check_timeout)
        except TimeoutError:
            return DependencyCheck(name=name, status="error", error="timeout")
        except Exception as exc:
            # Log details for us; return only the error type to the client.
            logger.warning("health_check_failed", check=name, error=str(exc))
            return DependencyCheck(name=name, status="error", error=type(exc).__name__)
        return DependencyCheck(
            name=name, status="ok", latency_ms=round((time.perf_counter() - start) * 1000, 1)
        )


def build_health_service(settings: Settings) -> HealthService:
    """Wire the real checkers."""
    return HealthService(
        settings,
        {"database": check_database, "redis": make_redis_checker(settings.redis_url)},
    )
