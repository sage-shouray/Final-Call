"""Async Redis client singleton, lifecycle-managed alongside the DB."""
import redis.asyncio as aioredis
import structlog

from src.config import settings

log = structlog.get_logger(__name__)

_redis: aioredis.Redis | None = None  # type: ignore[type-arg]


async def connect_redis() -> None:
    global _redis
    _redis = aioredis.from_url(
        str(settings.REDIS_URL),
        decode_responses=True,
        max_connections=20,
        # Deliberately short. Redis here is a local, optional dependency: every
        # caller already degrades gracefully without it (rate limiting passes
        # through, token blacklisting is skipped). A 5 s connect timeout meant
        # each call waited 5 s on ::1 and again on 127.0.0.1, then retried — so
        # with Redis down a login took 23 seconds instead of failing over
        # instantly. A local Redis answers in microseconds or not at all.
        socket_connect_timeout=1,
        socket_timeout=2,
        retry_on_timeout=False,
    )
    await _redis.ping()
    log.info("Redis connected", url=str(settings.REDIS_URL).split("@")[-1])


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None
        log.info("Redis connection closed")


def get_redis() -> aioredis.Redis:  # type: ignore[type-arg]
    if _redis is None:
        raise RuntimeError("Redis not initialised — call connect_redis() first")
    return _redis
