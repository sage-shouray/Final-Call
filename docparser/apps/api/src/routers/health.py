"""Health-check endpoints — liveness and readiness probes."""
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text

from src.config import settings

log = structlog.get_logger(__name__)
router = APIRouter(tags=["Health"])


class HealthResponse(BaseModel):
    status: str
    version: str
    database: str
    redis: str
    timestamp: str


@router.get("/health", response_model=HealthResponse, summary="Liveness probe")
async def health_check() -> HealthResponse:
    db_status = "up"
    try:
        from src.database import AsyncSessionLocal
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
    except Exception:
        db_status = "down"

    redis_status = "up"
    try:
        from src.utils.redis_client import get_redis
        await get_redis().ping()
    except Exception:
        redis_status = "down"

    overall = "healthy" if db_status == "up" and redis_status == "up" else "degraded"

    return HealthResponse(
        status=overall,
        version=settings.APP_VERSION,
        database=db_status,
        redis=redis_status,
        timestamp=datetime.now(UTC).isoformat(),
    )


@router.get("/health/ready", summary="Readiness probe")
async def readiness() -> dict[str, str]:
    return {"status": "ready"}
