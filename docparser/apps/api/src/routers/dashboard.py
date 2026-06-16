"""Dashboard metrics endpoint.

GET /api/dashboard/metrics

Returns aggregated KPIs for the main dashboard.  Results are cached in Redis
with a 60-second TTL.  The event consumer invalidates the cache on any
STATUS_CHANGED / OCR_COMPLETE / VALIDATION_COMPLETE / MIRO_POSTED event so
the dashboard reflects state changes within one cache cycle.
"""
from __future__ import annotations

import json
import math
from decimal import Decimal
from typing import Any

import structlog
from fastapi import APIRouter

from src.database import get_database
from src.middleware.auth import CurrentUser
from src.repositories.document_repository import DocumentRepository
from src.utils.redis_client import get_redis

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

_CACHE_KEY = "cache:dashboard:metrics"
_CACHE_TTL = 60  # seconds


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pct(part: int, total: int) -> float:
    return round(part / total * 100, 1) if total else 0.0


def _build_response(raw: dict[str, Any]) -> dict[str, Any]:
    """Transform the DocumentRepository aggregation result into the API shape."""
    by_status: dict[str, int] = raw.get("by_status", {})
    by_tcode: dict[str, int] = raw.get("by_tcode", {})
    by_type: dict[str, int] = raw.get("by_type", {})
    total = int(raw.get("total_documents", 0))

    total_processed = total
    posted_to_sap = by_status.get("posted", 0)
    pending_review = by_status.get("validated", 0)
    failed = by_status.get("failed", 0)

    # by_tcode as [{tcode, count, percentage}]
    by_tcode_list = [
        {"tcode": k, "count": v, "percentage": _pct(v, total)}
        for k, v in by_tcode.items()
    ]

    # by_status as [{status, count, percentage}]
    by_status_list = [
        {"status": k, "count": v, "percentage": _pct(v, total)}
        for k, v in by_status.items()
    ]

    # by_type as [{type, count}]
    by_type_list = [{"type": k, "count": v} for k, v in by_type.items()]

    # recent_trend keeps the existing format [{date, count}]
    recent_trend = [
        {"date": item.get("_id", ""), "count": item.get("count", 0)}
        for item in raw.get("recent_trend", [])
    ]

    return {
        "total_processed": total_processed,
        "posted_to_sap": posted_to_sap,
        "pending_review": pending_review,
        "failed": failed,
        "total_value_inr": raw.get("total_value", "0"),
        "by_tcode": by_tcode_list,
        "by_status": by_status_list,
        "by_type": by_type_list,
        "recent_trend": recent_trend,
    }


# ---------------------------------------------------------------------------
# GET /api/dashboard/metrics
# ---------------------------------------------------------------------------


@router.get(
    "/metrics",
    summary="Aggregated KPI metrics for the dashboard",
)
async def get_metrics(current_user: CurrentUser) -> dict[str, Any]:
    redis = get_redis()

    # Return cached result if fresh
    try:
        cached = await redis.get(_CACHE_KEY)
        if cached:
            return json.loads(cached)
    except Exception:
        pass  # Redis miss → compute fresh

    # Compute from MongoDB
    db = get_database()
    raw = await DocumentRepository(db).get_dashboard_metrics()
    result = _build_response(raw)

    # Cache for 60 s
    try:
        await redis.setex(_CACHE_KEY, _CACHE_TTL, json.dumps(result, default=str))
    except Exception as exc:
        log.warning("Dashboard cache write failed", error=str(exc))

    return result
