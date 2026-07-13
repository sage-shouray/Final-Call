"""Dashboard metrics endpoint."""
from __future__ import annotations

import json
from typing import Any

import structlog
from fastapi import APIRouter

from src.middleware.auth import CurrentUser
from src.repositories.document_repository import DocumentRepository
from src.utils.redis_client import get_redis

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

_CACHE_KEY = "cache:dashboard:metrics"
_CACHE_TTL = 60


def _pct(part: int, total: int) -> float:
    return round(part / total * 100, 1) if total else 0.0


def _build_response(raw: dict[str, Any]) -> dict[str, Any]:
    by_status: dict[str, int] = raw.get("by_status", {})
    by_tcode:  dict[str, int] = raw.get("by_tcode", {})
    by_type:   dict[str, int] = raw.get("by_type", {})
    total = int(raw.get("total_documents", 0))

    return {
        "total_processed": total,
        "posted_to_sap":   by_status.get("posted", 0),
        "pending_review":  by_status.get("validated", 0),
        "failed":          by_status.get("failed", 0),
        "total_value_inr": raw.get("total_value", "0"),
        "by_tcode":   [{"tcode": k, "count": v, "percentage": _pct(v, total)} for k, v in by_tcode.items()],
        "by_status":  [{"status": k, "count": v, "percentage": _pct(v, total)} for k, v in by_status.items()],
        "by_type":    [{"type": k, "count": v} for k, v in by_type.items()],
        "recent_trend": [
            {"date": item.get("_id", ""), "count": item.get("count", 0)}
            for item in raw.get("recent_trend", [])
        ],
    }


@router.get("/metrics", summary="Aggregated KPI metrics for the dashboard")
async def get_metrics(current_user: CurrentUser) -> dict[str, Any]:
    redis = get_redis()

    try:
        cached = await redis.get(_CACHE_KEY)
        if cached:
            return json.loads(cached)
    except Exception:
        pass

    from src.database import AsyncSessionLocal
    async with AsyncSessionLocal() as session:
        raw = await DocumentRepository(session).get_dashboard_metrics()

    result = _build_response(raw)

    try:
        await redis.setex(_CACHE_KEY, _CACHE_TTL, json.dumps(result, default=str))
    except Exception as exc:
        log.warning("Dashboard cache write failed", error=str(exc))

    return result
