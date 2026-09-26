"""Fixed-window counters in Redis, used for brute-force protection.

`hit()` counts one attempt and says how long to wait if the limit is exceeded.
Tests use `MemoryRateLimiter` (same behaviour, no Redis).
"""

import time
from collections.abc import AsyncIterator
from typing import Annotated, Protocol

from fastapi import Depends
from redis.asyncio import Redis

from app.core.config import Settings, get_settings


class RateLimiter(Protocol):
    """Counts attempts per key inside a time window."""

    async def hit(self, key: str, *, limit: int, window_seconds: int) -> int | None:
        """Count one attempt. Returns seconds to wait if over the limit, else None."""
        ...

    async def count(self, key: str) -> tuple[int, int]:
        """(attempts in the current window, seconds until the window ends)."""
        ...

    async def reset(self, key: str) -> None:
        """Forget all attempts for a key (e.g. after a successful login)."""
        ...


class RedisRateLimiter:
    """Redis implementation: INCR + EXPIRE, one key per counter."""

    PREFIX = "ratelimit:"

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def hit(self, key: str, *, limit: int, window_seconds: int) -> int | None:
        """Count one attempt."""
        full = self.PREFIX + key
        pipe = self._redis.pipeline()
        pipe.incr(full)
        pipe.expire(full, window_seconds, nx=True)
        pipe.ttl(full)
        count, _, ttl = await pipe.execute()
        if int(count) > limit:
            return max(int(ttl), 1)
        return None

    async def count(self, key: str) -> tuple[int, int]:
        """Current attempts and remaining window."""
        full = self.PREFIX + key
        pipe = self._redis.pipeline()
        pipe.get(full)
        pipe.ttl(full)
        value, ttl = await pipe.execute()
        return (int(value or 0), max(int(ttl), 0))

    async def reset(self, key: str) -> None:
        """Delete the counter."""
        await self._redis.delete(self.PREFIX + key)


class MemoryRateLimiter:
    """In-process implementation for tests."""

    def __init__(self) -> None:
        self._data: dict[str, tuple[int, float]] = {}

    def _get(self, key: str) -> tuple[int, float]:
        count, expires = self._data.get(key, (0, 0.0))
        if expires <= time.monotonic():
            return (0, 0.0)
        return (count, expires)

    async def hit(self, key: str, *, limit: int, window_seconds: int) -> int | None:
        """Count one attempt."""
        count, expires = self._get(key)
        if count == 0:
            expires = time.monotonic() + window_seconds
        self._data[key] = (count + 1, expires)
        if count + 1 > limit:
            return max(int(expires - time.monotonic()), 1)
        return None

    async def count(self, key: str) -> tuple[int, int]:
        """Current attempts and remaining window."""
        count, expires = self._get(key)
        return (count, max(int(expires - time.monotonic()), 0))

    async def reset(self, key: str) -> None:
        """Delete the counter."""
        self._data.pop(key, None)


async def get_rate_limiter(
    settings: Annotated[Settings, Depends(get_settings)],
) -> AsyncIterator[RateLimiter]:
    """FastAPI dependency: a Redis-backed limiter for this request (overridden in tests)."""
    client = Redis.from_url(settings.redis_url, socket_timeout=2, socket_connect_timeout=2)
    try:
        yield RedisRateLimiter(client)
    finally:
        await client.aclose()
