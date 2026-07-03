"""Customer endpoints for Sales Order (VA01) flow.

GET  /api/customers/search?q=...   — search customers directly from SAP API
POST /api/customers/sync            — optional: bulk-sync SAP → MongoDB for faster future lookups
"""
from typing import Annotated

import aiohttp
import structlog
from fastapi import APIRouter, HTTPException, Query

from src.config import settings
from src.middleware.auth import CurrentUser

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/customers", tags=["Customers"])

_COLLECTION = "customers"
# SAP customer fetch can take 60-180 s for large datasets — use a dedicated long timeout
_SAP_CUSTOMER_TIMEOUT = aiohttp.ClientTimeout(total=180)


def _sap_customer_url() -> str:
    base = settings.SAP_BASE_URL.rstrip("/")
    client = settings.SAP_CLIENT
    return f"{base}/ZCUSTOMER/CUSTOMER?sap-client={client}"


async def _fetch_from_sap() -> list[dict]:
    """Fetch all customers directly from SAP with a 3-minute timeout."""
    url = _sap_customer_url()
    auth = None
    if getattr(settings, "SAP_USERNAME", None) and getattr(settings, "SAP_PASSWORD", None):
        auth = aiohttp.BasicAuth(settings.SAP_USERNAME, settings.SAP_PASSWORD)

    async with aiohttp.ClientSession(timeout=_SAP_CUSTOMER_TIMEOUT, auth=auth) as session:
        async with session.get(url) as resp:
            resp.raise_for_status()
            raw = await resp.json(content_type=None)

    if isinstance(raw, list):
        return raw
    # Handle OData/SAP envelope formats
    return (
        raw.get("CUSTOMERS")
        or raw.get("customers")
        or raw.get("value")
        or (raw.get("d") or {}).get("results", [])
        or []
    )


def _normalize(text: str) -> str:
    """Lowercase and remove all spaces for fuzzy matching."""
    return str(text).lower().replace(" ", "").replace("-", "")


def _filter_customers(all_customers: list[dict], query: str, limit: int) -> list[dict]:
    """Match customers using multiple strategies — handles OCR spacing/casing differences."""
    q_raw   = query.lower().strip()          # "gulshan new partner 3"
    q_norm  = _normalize(query)              # "gulshanewpartner3"
    q_words = set(q_raw.split())             # {"gulshan", "new", "partner", "3"}

    scored = []
    for c in all_customers:
        name     = str(c.get("CUSTOMER_NAME", ""))
        name_raw = name.lower().strip()
        name_norm = _normalize(name)

        if q_norm == name_norm:                          # exact normalized match
            score = 100
        elif q_raw == name_raw:                          # exact raw match
            score = 90
        elif q_norm in name_norm or name_norm in q_norm: # substring normalized
            score = 80
        elif q_raw in name_raw or name_raw in q_raw:     # substring raw
            score = 70
        else:
            # word overlap — how many query words appear in the name
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


# ---------------------------------------------------------------------------
# GET /api/customers/search
# ---------------------------------------------------------------------------

@router.get("/search")
async def search_customers(
    current_user: CurrentUser,
    q: Annotated[str, Query(min_length=1)] = "",
    limit: int = 10,
):
    """
    Search customers by name/ID.
    1. Tries MongoDB first (fast, if sync has been done).
    2. Falls back to live SAP API if MongoDB returns nothing.
    """
    if not q:
        return {"customers": [], "total": 0}

    # ── 1. Try MongoDB (instant if synced) ──────────────────────────────────
    try:
        from src.database import get_database
        db = get_database()
        collection = db[_COLLECTION]

        mongo_results: list[dict] = []
        try:
            cursor = collection.find(
                {"$text": {"$search": q}},
                {"score": {"$meta": "textScore"}},
            ).sort([("score", {"$meta": "textScore"})]).limit(limit)
            async for doc in cursor:
                doc.pop("_id", None)
                mongo_results.append(doc)
        except Exception:
            cursor = collection.find(
                {"CUSTOMER_NAME": {"$regex": q, "$options": "i"}},
            ).limit(limit)
            async for doc in cursor:
                doc.pop("_id", None)
                mongo_results.append(doc)

        if mongo_results:
            log.info("customer search → MongoDB", query=q, count=len(mongo_results))
            return {"customers": mongo_results, "total": len(mongo_results), "source": "mongodb"}
    except Exception as mongo_err:
        log.warning("MongoDB unavailable, going to SAP", error=str(mongo_err))

    # ── 2. Direct SAP API call (always works, just slower) ──────────────────
    log.info("customer search → SAP direct", query=q)
    try:
        all_customers = await _fetch_from_sap()
    except aiohttp.ClientResponseError as exc:
        log.error("SAP customer API error", status=exc.status, url=exc.request_info.url)
        raise HTTPException(status_code=502, detail=f"SAP API returned {exc.status}")
    except Exception as exc:
        log.error("SAP customer fetch failed", error=str(exc))
        raise HTTPException(status_code=502, detail="Could not reach SAP customer API")

    results = _filter_customers(all_customers, q, limit)
    log.info("SAP customer search done", query=q, total_from_sap=len(all_customers), matched=len(results))

    # Cache found customers into MongoDB for future fast lookups
    if results:
        try:
            from pymongo import UpdateOne
            from src.database import get_database
            db = get_database()
            ops = [
                UpdateOne({"CUSTOMER": c["CUSTOMER"]}, {"$set": c}, upsert=True)
                for c in results if c.get("CUSTOMER")
            ]
            if ops:
                await db[_COLLECTION].bulk_write(ops, ordered=False)
        except Exception:
            pass  # cache failure is non-fatal

    return {"customers": results, "total": len(results), "source": "sap_live"}


# ---------------------------------------------------------------------------
# POST /api/customers/sync  (optional one-time bulk load)
# ---------------------------------------------------------------------------

@router.post("/sync")
async def sync_customers(current_user: CurrentUser):
    """Pull ALL customers from SAP and upsert into MongoDB (run once for fast future searches)."""
    log.info("customer bulk sync started", triggered_by=current_user.id)

    try:
        all_customers = await _fetch_from_sap()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"SAP fetch failed: {exc}")

    if not all_customers:
        return {"synced": 0, "message": "No customers returned from SAP"}

    from pymongo import UpdateOne
    from src.database import get_database
    db = get_database()
    collection = db[_COLLECTION]

    batch: list = []
    synced = 0
    for c in all_customers:
        customer_id = c.get("CUSTOMER") or c.get("customer")
        if not customer_id:
            continue
        batch.append(UpdateOne({"CUSTOMER": customer_id}, {"$set": c}, upsert=True))
        synced += 1
        if len(batch) >= 1000:
            await collection.bulk_write(batch, ordered=False)
            batch = []

    if batch:
        await collection.bulk_write(batch, ordered=False)

    try:
        await collection.create_index([
            ("CUSTOMER_NAME", "text"),
            ("CITY", "text"),
            ("CUSTOMER", "text"),
        ])
    except Exception:
        pass

    log.info("customer bulk sync complete", synced=synced)
    return {"synced": synced, "message": f"Synced {synced} customers from SAP into MongoDB"}
