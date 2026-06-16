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
        socket_connect_timeout=5,
        socket_timeout=5,
        retry_on_timeout=True,
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
