"""Customer endpoints for Sales Order (VA01) flow.

GET  /api/customers/search?q=...   — search customers directly from SAP API
POST /api/customers/sync            — optional: bulk-sync SAP → PostgreSQL for faster future lookups
"""
import uuid
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.config import settings
from src.database import AsyncSessionLocal
from src.middleware.auth import CurrentUser

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/customers", tags=["Customers"])

_SAP_CUSTOMER_TIMEOUT = 180  # seconds


def _sap_customer_url() -> str:
    base = settings.SAP_BASE_URL.rstrip("/")
    return f"{base}/ZCUSTOMER/CUSTOMER?sap-client={settings.SAP_CLIENT}"


async def _fetch_from_sap() -> list[dict]:
    """Fetch all customers directly from SAP with a long timeout."""
    import httpx

    url = _sap_customer_url()
    auth = None
    if getattr(settings, "SAP_USERNAME", None) and getattr(settings, "SAP_PASSWORD", None):
        auth = (settings.SAP_USERNAME, settings.SAP_PASSWORD.get_secret_value())

    async with httpx.AsyncClient(timeout=_SAP_CUSTOMER_TIMEOUT, auth=auth) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        raw = resp.json()

    if isinstance(raw, list):
        return raw
    return (
        raw.get("CUSTOMERS")
        or raw.get("customers")
        or raw.get("value")
        or (raw.get("d") or {}).get("results", [])
        or []
    )


def _normalize(text_: str) -> str:
    return str(text_).lower().replace(" ", "").replace("-", "")


def _filter_customers(all_customers: list[dict], query: str, limit: int) -> list[dict]:
    q_raw   = query.lower().strip()
    q_norm  = _normalize(query)
    q_words = set(q_raw.split())

    scored = []
    for c in all_customers:
        name      = str(c.get("CUSTOMER_NAME", ""))
        name_raw  = name.lower().strip()
        name_norm = _normalize(name)

        if q_norm == name_norm:
            score = 100
        elif q_raw == name_raw:
            score = 90
        elif q_norm in name_norm or name_norm in q_norm:
            score = 80
        elif q_raw in name_raw or name_raw in q_raw:
            score = 70
        else:
            name_words = set(name_raw.split())
            overlap = len(q_words & name_words)
            if overlap == 0:
                continue
            score = int(overlap / max(len(q_words), len(name_words)) * 60)
            if score < 30:
                continue

        scored.append((score, c))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in scored[:limit]]


async def _pg_search(query: str, limit: int) -> list[dict[str, Any]]:
    """Try a full-text search in the local PostgreSQL customer cache."""
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                text("""
                    SELECT data FROM customers
                    WHERE to_tsvector('english',
                        coalesce(data->>'CUSTOMER_NAME','') || ' ' ||
                        coalesce(data->>'CITY','') || ' ' ||
                        coalesce(customer_id,''))
                    @@ plainto_tsquery('english', :q)
                    ORDER BY ts_rank(
                        to_tsvector('english',
                            coalesce(data->>'CUSTOMER_NAME','') || ' ' ||
                            coalesce(data->>'CITY','') || ' ' ||
                            coalesce(customer_id,'')),
                        plainto_tsquery('english', :q)
                    ) DESC
                    LIMIT :lim
                """),
                {"q": query, "lim": limit},
            )
            return [row[0] for row in result.all()]
    except Exception:
        return []


async def _pg_upsert(customers: list[dict]) -> None:
    """Cache a batch of SAP customers into PostgreSQL."""
    try:
        async with AsyncSessionLocal() as session:
            for c in customers:
                cid = c.get("CUSTOMER") or c.get("customer")
                if not cid:
                    continue
                await session.execute(
                    text("""
                        INSERT INTO customers (id, customer_id, data)
                        VALUES (:id, :cid, :data::jsonb)
                        ON CONFLICT (customer_id) DO UPDATE SET data = EXCLUDED.data
                    """),
                    {"id": str(uuid.uuid4()), "cid": str(cid), "data": str(c).replace("'", '"')},
                )
            await session.commit()
    except Exception as exc:
        log.warning("PostgreSQL customer cache write failed", error=str(exc))


# ---------------------------------------------------------------------------
# GET /api/customers/search
# ---------------------------------------------------------------------------


@router.get("/search")
async def search_customers(
    current_user: CurrentUser,
    q: Annotated[str, Query(min_length=1)] = "",
    limit: int = 10,
):
    if not q:
        return {"customers": [], "total": 0}

    # 1. Try PostgreSQL cache (fast if synced)
    pg_results = await _pg_search(q, limit)
    if pg_results:
        log.info("customer search → PostgreSQL cache", query=q, count=len(pg_results))
        return {"customers": pg_results, "total": len(pg_results), "source": "postgresql"}

    # 2. Direct SAP API call (always works, just slower)
    log.info("customer search → SAP direct", query=q)
    try:
        all_customers = await _fetch_from_sap()
    except Exception as exc:
        log.error("SAP customer fetch failed", error=str(exc))
        raise HTTPException(status_code=502, detail="Could not reach SAP customer API")

    results = _filter_customers(all_customers, q, limit)
    log.info("SAP customer search done", query=q, total_from_sap=len(all_customers), matched=len(results))

    if results:
        import asyncio
        asyncio.create_task(_pg_upsert(results))

    return {"customers": results, "total": len(results), "source": "sap_live"}


# ---------------------------------------------------------------------------
# POST /api/customers/sync
# ---------------------------------------------------------------------------


@router.post("/sync")
async def sync_customers(current_user: CurrentUser):
    """Pull ALL customers from SAP and upsert into PostgreSQL."""
    log.info("customer bulk sync started", triggered_by=current_user.id)

    try:
        all_customers = await _fetch_from_sap()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"SAP fetch failed: {exc}")

    if not all_customers:
        return {"synced": 0, "message": "No customers returned from SAP"}

    synced = 0
    try:
        async with AsyncSessionLocal() as session:
            for c in all_customers:
                cid = c.get("CUSTOMER") or c.get("customer")
                if not cid:
                    continue
                import json
                await session.execute(
                    text("""
                        INSERT INTO customers (id, customer_id, data)
                        VALUES (:id, :cid, :data::jsonb)
                        ON CONFLICT (customer_id) DO UPDATE SET data = EXCLUDED.data
                    """),
                    {"id": str(uuid.uuid4()), "cid": str(cid), "data": json.dumps(c)},
                )
                synced += 1
            await session.commit()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Database write failed: {exc}")

    log.info("customer bulk sync complete", synced=synced)
    return {"synced": synced, "message": f"Synced {synced} customers from SAP into PostgreSQL"}
