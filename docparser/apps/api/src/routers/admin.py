"""Super Admin API — tenant/company management, billing, activity monitor."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select, text

from src.database import AsyncSessionLocal
from src.middleware.auth import CurrentUser
from src.models.tenant import (
    BillingRecordRow, PricingConfigRow, TenantApiConfigRow, TenantRow,
)
from src.models.user import UserRow
from src.models.document import DocumentRow

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])


def _require_super_admin(user: CurrentUser) -> None:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Super admin access required.")


# ---------------------------------------------------------------------------
# Overview stats
# ---------------------------------------------------------------------------

@router.get("/overview")
async def get_overview(current_user: CurrentUser) -> dict[str, Any]:
    _require_super_admin(current_user)
    async with AsyncSessionLocal() as session:
        total_companies = (await session.execute(select(func.count()).select_from(TenantRow))).scalar() or 0
        total_users     = (await session.execute(select(func.count()).select_from(UserRow))).scalar() or 0
        total_docs      = (await session.execute(select(func.count()).select_from(DocumentRow))).scalar() or 0
        total_pages     = (await session.execute(select(func.coalesce(func.sum(DocumentRow.page_count), 0)))).scalar() or 0

        # Revenue this month
        now = datetime.now(UTC)
        rev = (await session.execute(
            select(func.coalesce(func.sum(BillingRecordRow.total_amount), 0))
            .where(BillingRecordRow.period_month == now.month)
            .where(BillingRecordRow.period_year  == now.year)
        )).scalar() or 0

        return {
            "total_companies":    total_companies,
            "total_users":        total_users,
            "total_documents":    total_docs,
            "total_pages":        int(total_pages),
            "revenue_this_month": float(rev),
        }


# ---------------------------------------------------------------------------
# Companies (tenants) CRUD
# ---------------------------------------------------------------------------

@router.get("/companies")
async def list_companies(current_user: CurrentUser) -> list[dict[str, Any]]:
    _require_super_admin(current_user)
    async with AsyncSessionLocal() as session:
        tenants = (await session.execute(select(TenantRow).order_by(TenantRow.created_at))).scalars().all()
        result = []
        for t in tenants:
            doc_count  = (await session.execute(select(func.count()).select_from(DocumentRow).where(DocumentRow.tenant_id == t.id))).scalar() or 0
            page_count = (await session.execute(select(func.coalesce(func.sum(DocumentRow.page_count), 0)).where(DocumentRow.tenant_id == t.id))).scalar() or 0
            user_count = (await session.execute(select(func.count()).select_from(UserRow).where(UserRow.tenant_id == t.id))).scalar() or 0
            last_doc   = (await session.execute(
                select(DocumentRow.uploaded_at).where(DocumentRow.tenant_id == t.id).order_by(DocumentRow.uploaded_at.desc()).limit(1)
            )).scalar()
            rev = (await session.execute(
                select(func.coalesce(func.sum(BillingRecordRow.total_amount), 0))
                .where(BillingRecordRow.tenant_id == t.id)
            )).scalar() or 0

            row = t.to_dict()
            row.update({
                "doc_count":       doc_count,
                "page_count":      int(page_count),
                "user_count":      user_count,
                "last_activity":   last_doc.isoformat() if last_doc else None,
                "total_billed":    float(rev),
            })
            result.append(row)
        return result


@router.post("/companies", status_code=201)
async def create_company(body: dict[str, Any], current_user: CurrentUser) -> dict[str, Any]:
    _require_super_admin(current_user)
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="Company name is required.")
    slug = body.get("slug") or name.lower().replace(" ", "-")
    tenant_id = f"tenant-{uuid.uuid4().hex[:8]}"

    async with AsyncSessionLocal() as session:
        tenant = TenantRow(
            id=tenant_id, name=name, slug=slug,
            gstin=body.get("gstin", ""), email=body.get("email", ""),
            phone=body.get("phone", ""), address=body.get("address", ""),
            status="active", is_active=True,
        )
        session.add(tenant)
        await session.flush()   # write tenant row so FK constraints pass

        # Seed default pricing
        defaults = [
            ("MIRO",         "MIRO - Vendor Invoice",   150),
            ("MIRO_SERVICE", "MIRO - Service Invoice",  150),
            ("MIRO_FREIGHT", "MIRO - Freight Invoice",  120),
            ("MIGO",         "MIGO / GRN Posting",      100),
            ("FB60",         "FB60 - Non-PO Invoice",   130),
            ("F26",          "F-26 - Customer Payment", 100),
            ("VA01",         "VA01 - Sales Order",      200),
        ]
        for tcode, label, price in defaults:
            session.add(PricingConfigRow(tenant_id=tenant_id, tcode=tcode, label=label, price_per_document=price))

        # Seed API configs (empty URLs — admin fills them in)
        api_defaults = [
            ("po_detail",    "PO & GRN Detail",         "validation", "zpo_grn/Detail",                    "GET"),
            ("miro_post",    "MIRO (Material PO)",       "miro",       "ZMIRO/MIRO",                        "POST"),
            ("miro_service", "MIRO (Service PO)",        "miro",       "zmiro_post/MIRO",                   "POST"),
            ("grn_post",     "GRN / MIGO Posting",      "grn",        "ZMIGO/GRN",                         "POST"),
            ("spo_detail",   "Service PO Detail",        "validation", "zspodetail/Detail",                 "GET"),
            ("customer",     "Customer Master",          "so",         "ZCUSTOMER/CUSTOMER",                "GET"),
            ("so_create",    "Sales Order Create",       "so",         "ZCREATE_SALESOR/SALESORDER_CREATE", "POST"),
            ("so_simulate",  "Sales Order Simulate",     "so",         "ZDATA_HOLD/DATA_SIMULATE",          "POST"),
            ("f26_payment",  "F-26 Customer Payment",    "f26",        "ZINV_PAY/INV_PAYMENT",              "POST"),
            ("fb60_post",    "FB60 Non-PO Invoice",      "fb60",       "zfb60/fb60post",                    "POST"),
        ]
        for api_key, label, workflow, path, method in api_defaults:
            session.add(TenantApiConfigRow(
                tenant_id=tenant_id, api_key=api_key, label=label,
                workflow=workflow, base_url="", path=path, method=method, sap_client="800",
            ))

        await session.commit()
        await session.refresh(tenant)
        return tenant.to_dict()


@router.delete("/companies/{tenant_id}", status_code=204)
async def delete_company(tenant_id: str, current_user: CurrentUser) -> None:
    _require_super_admin(current_user)
    async with AsyncSessionLocal() as session:
        tenant = (await session.execute(select(TenantRow).where(TenantRow.id == tenant_id))).scalar_one_or_none()
        if not tenant:
            raise HTTPException(status_code=404, detail="Company not found.")

        await session.execute(text("DELETE FROM documents WHERE tenant_id = :tid"), {"tid": tenant_id})
        await session.execute(text("DELETE FROM users WHERE tenant_id = :tid"), {"tid": tenant_id})
        await session.execute(text("DELETE FROM pricing_configs WHERE tenant_id = :tid"), {"tid": tenant_id})
        await session.execute(text("DELETE FROM tenant_api_configs WHERE tenant_id = :tid"), {"tid": tenant_id})
        await session.execute(text("DELETE FROM billing_records WHERE tenant_id = :tid"), {"tid": tenant_id})
        await session.delete(tenant)
        await session.commit()


@router.get("/companies/{tenant_id}")
async def get_company(tenant_id: str, current_user: CurrentUser) -> dict[str, Any]:
    _require_super_admin(current_user)
    async with AsyncSessionLocal() as session:
        tenant = (await session.execute(select(TenantRow).where(TenantRow.id == tenant_id))).scalar_one_or_none()
        if not tenant:
            raise HTTPException(status_code=404, detail="Company not found.")
        return tenant.to_dict()


@router.put("/companies/{tenant_id}")
async def update_company(tenant_id: str, body: dict[str, Any], current_user: CurrentUser) -> dict[str, Any]:
    _require_super_admin(current_user)
    async with AsyncSessionLocal() as session:
        tenant = (await session.execute(select(TenantRow).where(TenantRow.id == tenant_id))).scalar_one_or_none()
        if not tenant:
            raise HTTPException(status_code=404, detail="Company not found.")
        for field in ("name", "gstin", "email", "phone", "address", "status"):
            if field in body:
                setattr(tenant, field, body[field])
        if "is_active" in body:
            tenant.is_active = bool(body["is_active"])
        await session.commit()
        await session.refresh(tenant)
        return tenant.to_dict()


# ---------------------------------------------------------------------------
# Company users
# ---------------------------------------------------------------------------

@router.get("/companies/{tenant_id}/users")
async def get_company_users(tenant_id: str, current_user: CurrentUser) -> list[dict[str, Any]]:
    _require_super_admin(current_user)
    async with AsyncSessionLocal() as session:
        users = (await session.execute(
            select(UserRow).where(UserRow.tenant_id == tenant_id).order_by(UserRow.email)
        )).scalars().all()
        result = []
        for u in users:
            doc_count = (await session.execute(
                select(func.count()).select_from(DocumentRow).where(DocumentRow.uploaded_by == u.id)
            )).scalar() or 0
            d = u.to_dict()
            d["doc_count"] = doc_count
            result.append(d)
        return result


@router.post("/companies/{tenant_id}/users", status_code=201)
async def add_company_user(tenant_id: str, body: dict[str, Any], current_user: CurrentUser) -> dict[str, Any]:
    _require_super_admin(current_user)
    from src.services.auth_service import AuthService
    email    = (body.get("email") or "").strip().lower()
    name     = (body.get("name") or "").strip()
    role     = body.get("role", "operator")
    password = body.get("password", "")
    if not email or not name or not password:
        raise HTTPException(status_code=422, detail="email, name, and password are required.")
    if len(password) < 8:
        raise HTTPException(status_code=422, detail="Password must be at least 8 characters.")

    async with AsyncSessionLocal() as session:
        existing = (await session.execute(select(UserRow).where(UserRow.email == email))).scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=409, detail="Email already exists.")
        hashed = AuthService().hash_password(password)
        user = UserRow(
            email=email, name=name, role=role,
            hashed_password=hashed,
            tenant_id=tenant_id, is_active=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user.to_dict()


@router.put("/companies/{tenant_id}/users/{user_id}")
async def update_company_user(tenant_id: str, user_id: str, body: dict[str, Any], current_user: CurrentUser) -> dict[str, Any]:
    _require_super_admin(current_user)
    from src.services.auth_service import AuthService
    async with AsyncSessionLocal() as session:
        user = (await session.execute(select(UserRow).where(UserRow.id == user_id, UserRow.tenant_id == tenant_id))).scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="User not found.")
        for field in ("name", "role"):
            if field in body:
                setattr(user, field, body[field])
        if "is_active" in body:
            user.is_active = bool(body["is_active"])
        if body.get("new_password"):
            if len(body["new_password"]) < 8:
                raise HTTPException(status_code=422, detail="Password must be at least 8 characters.")
            user.hashed_password = AuthService().hash_password(body["new_password"])
        await session.commit()
        await session.refresh(user)
        return user.to_dict()


@router.delete("/companies/{tenant_id}/users/{user_id}", status_code=204)
async def delete_company_user(tenant_id: str, user_id: str, current_user: CurrentUser) -> None:
    _require_super_admin(current_user)
    if user_id == current_user.sub:
        raise HTTPException(status_code=400, detail="You cannot delete your own account.")
    async with AsyncSessionLocal() as session:
        user = (await session.execute(select(UserRow).where(UserRow.id == user_id, UserRow.tenant_id == tenant_id))).scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="User not found.")
        await session.delete(user)
        await session.commit()


# ---------------------------------------------------------------------------
# Company documents
# ---------------------------------------------------------------------------

@router.get("/companies/{tenant_id}/documents")
async def get_company_documents(
    tenant_id: str, current_user: CurrentUser,
    page: int = 1, limit: int = 20,
    user_id: str = "", status: str = "",
) -> dict[str, Any]:
    _require_super_admin(current_user)
    async with AsyncSessionLocal() as session:
        stmt = select(DocumentRow).where(DocumentRow.tenant_id == tenant_id)
        if user_id:
            stmt = stmt.where(DocumentRow.uploaded_by == user_id)
        if status:
            stmt = stmt.where(DocumentRow.status == status)
        stmt = stmt.order_by(DocumentRow.uploaded_at.desc())

        total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0
        docs  = (await session.execute(stmt.offset((page - 1) * limit).limit(limit))).scalars().all()

        return {
            "documents": [d.to_dict() for d in docs],
            "total":     total,
            "page":      page,
            "limit":     limit,
            "pages":     max(1, -(-total // limit)),
        }


# ---------------------------------------------------------------------------
# Company API configs
# ---------------------------------------------------------------------------

@router.get("/companies/{tenant_id}/apis")
async def get_company_apis(tenant_id: str, current_user: CurrentUser) -> list[dict[str, Any]]:
    _require_super_admin(current_user)
    async with AsyncSessionLocal() as session:
        apis = (await session.execute(
            select(TenantApiConfigRow).where(TenantApiConfigRow.tenant_id == tenant_id).order_by(TenantApiConfigRow.workflow, TenantApiConfigRow.api_key)
        )).scalars().all()
        return [a.to_dict() for a in apis]


@router.put("/companies/{tenant_id}/apis/{api_key}")
async def update_company_api(tenant_id: str, api_key: str, body: dict[str, Any], current_user: CurrentUser) -> dict[str, Any]:
    _require_super_admin(current_user)
    async with AsyncSessionLocal() as session:
        api = (await session.execute(
            select(TenantApiConfigRow).where(TenantApiConfigRow.tenant_id == tenant_id, TenantApiConfigRow.api_key == api_key)
        )).scalar_one_or_none()
        if not api:
            raise HTTPException(status_code=404, detail="API config not found.")
        for field in ("base_url", "path", "method", "sap_client", "auth_type", "username", "password", "is_active"):
            if field in body:
                setattr(api, field, body[field])
        await session.commit()
        await session.refresh(api)
        return api.to_dict()


@router.post("/companies/{tenant_id}/apis/{api_key}/test")
async def test_company_api(tenant_id: str, api_key: str, current_user: CurrentUser) -> dict[str, Any]:
    _require_super_admin(current_user)
    async with AsyncSessionLocal() as session:
        api = (await session.execute(
            select(TenantApiConfigRow).where(TenantApiConfigRow.tenant_id == tenant_id, TenantApiConfigRow.api_key == api_key)
        )).scalar_one_or_none()
        if not api:
            raise HTTPException(status_code=404, detail="API config not found.")

        if not api.base_url:
            return {"success": False, "message": "Base URL not configured."}

        import httpx
        url = f"{api.base_url.rstrip('/')}/{api.path.lstrip('/')}?sap-client={api.sap_client}"
        auth = (api.username, api.password) if api.username else None
        try:
            async with httpx.AsyncClient(timeout=10.0, auth=auth) as client:
                if api.method == "GET":
                    resp = await client.get(url, headers={"Accept": "application/json"})
                else:
                    resp = await client.post(url, json={}, headers={"Content-Type": "application/json"})
            success      = resp.status_code < 500
            test_status  = "ok" if success else "failed"
            message      = f"HTTP {resp.status_code}"
        except Exception as exc:
            success     = False
            test_status = "failed"
            message     = str(exc)

        api.last_tested_at   = datetime.now(UTC)
        api.last_test_status = test_status
        await session.commit()
        return {"success": success, "message": message, "status_code": resp.status_code if success else None}


# ---------------------------------------------------------------------------
# Company pricing
# ---------------------------------------------------------------------------

@router.get("/companies/{tenant_id}/pricing")
async def get_company_pricing(tenant_id: str, current_user: CurrentUser) -> list[dict[str, Any]]:
    _require_super_admin(current_user)
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(PricingConfigRow).where(PricingConfigRow.tenant_id == tenant_id).order_by(PricingConfigRow.tcode)
        )).scalars().all()
        return [r.to_dict() for r in rows]


@router.put("/companies/{tenant_id}/pricing/{tcode}")
async def update_company_pricing(tenant_id: str, tcode: str, body: dict[str, Any], current_user: CurrentUser) -> dict[str, Any]:
    _require_super_admin(current_user)
    async with AsyncSessionLocal() as session:
        row = (await session.execute(
            select(PricingConfigRow).where(PricingConfigRow.tenant_id == tenant_id, PricingConfigRow.tcode == tcode)
        )).scalar_one_or_none()
        if not row:
            raise HTTPException(status_code=404, detail="Pricing config not found.")
        if "price_per_document" in body:
            row.price_per_document = float(body["price_per_document"])
        if "label" in body:
            row.label = body["label"]
        await session.commit()
        await session.refresh(row)
        return row.to_dict()


# ---------------------------------------------------------------------------
# Billing
# ---------------------------------------------------------------------------

@router.get("/companies/{tenant_id}/billing")
async def get_company_billing(tenant_id: str, current_user: CurrentUser) -> dict[str, Any]:
    _require_super_admin(current_user)
    now = datetime.now(UTC)
    async with AsyncSessionLocal() as session:
        # Auto-calculate current month billing from documents
        rows = (await session.execute(text("""
            SELECT d.tcode, COUNT(*) as doc_count
            FROM documents d
            WHERE d.tenant_id = :tid
              AND EXTRACT(MONTH FROM d.uploaded_at) = :month
              AND EXTRACT(YEAR  FROM d.uploaded_at) = :year
              AND d.status IN ('posted','gr_posted','validated','simulated')
            GROUP BY d.tcode
        """), {"tid": tenant_id, "month": now.month, "year": now.year})).fetchall()

        pricing: dict[str, PricingConfigRow] = {r.tcode: r for r in (await session.execute(
            select(PricingConfigRow).where(PricingConfigRow.tenant_id == tenant_id)
        )).scalars().all()}

        line_items = []
        total = 0.0
        for row in rows:
            tcode     = row[0]
            doc_count = row[1]
            p         = pricing.get(tcode)
            price     = float(p.price_per_document) if p else 0.0
            amount    = doc_count * price
            total    += amount
            line_items.append({
                "tcode":      tcode,
                "label":      p.label if p else tcode,
                "doc_count":  doc_count,
                "price_each": price,
                "amount":     amount,
            })

        # Historical billing records
        history = (await session.execute(
            select(BillingRecordRow).where(BillingRecordRow.tenant_id == tenant_id).order_by(BillingRecordRow.period_year.desc(), BillingRecordRow.period_month.desc())
        )).scalars().all()

        return {
            "tenant_id":    tenant_id,
            "period_month": now.month,
            "period_year":  now.year,
            "line_items":   line_items,
            "total_due":    total,
            "history":      [r.to_dict() for r in history],
        }


_MONTH_NAMES = [
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


async def _compute_tenant_month_billing(session: Any, tenant_id: str, month: int, year: int) -> dict[str, Any]:
    """Live cost computation for one tenant/month — same logic as the per-company billing endpoint."""
    rows = (await session.execute(text("""
        SELECT d.tcode, COUNT(*) as doc_count, COALESCE(SUM(d.page_count), 0) as page_count
        FROM documents d
        WHERE d.tenant_id = :tid
          AND EXTRACT(MONTH FROM d.uploaded_at) = :month
          AND EXTRACT(YEAR  FROM d.uploaded_at) = :year
          AND d.status IN ('posted','gr_posted','validated','simulated')
        GROUP BY d.tcode
    """), {"tid": tenant_id, "month": month, "year": year})).fetchall()

    pricing: dict[str, PricingConfigRow] = {r.tcode: r for r in (await session.execute(
        select(PricingConfigRow).where(PricingConfigRow.tenant_id == tenant_id)
    )).scalars().all()}

    total_documents = 0
    total_pages = 0
    total_amount = 0.0
    for row in rows:
        tcode, doc_count, page_count = row[0], row[1], row[2]
        price = float(pricing[tcode].price_per_document) if tcode in pricing else 0.0
        total_documents += doc_count
        total_pages += int(page_count)
        total_amount += doc_count * price

    return {"total_documents": total_documents, "total_pages": total_pages, "total_amount": total_amount}


@router.get("/billing")
async def get_all_billing(current_user: CurrentUser) -> dict[str, Any]:
    _require_super_admin(current_user)
    now = datetime.now(UTC)
    async with AsyncSessionLocal() as session:
        tenants = (await session.execute(select(TenantRow).where(TenantRow.is_active == True).order_by(TenantRow.name))).scalars().all()

        records: list[dict[str, Any]] = []
        total_revenue = 0.0
        this_month = 0.0
        for t in tenants:
            live = await _compute_tenant_month_billing(session, t.id, now.month, now.year)
            # All-time revenue = historical recorded charges + this month's live total
            paid_history = (await session.execute(
                select(func.coalesce(func.sum(BillingRecordRow.total_amount), 0))
                .where(BillingRecordRow.tenant_id == t.id)
            )).scalar() or 0
            tenant_total_revenue = float(paid_history) + live["total_amount"]

            records.append({
                "tenant_id":       t.id,
                "company_name":    t.name,
                "month":           f"{_MONTH_NAMES[now.month]} {now.year}",
                "total_documents": live["total_documents"],
                "total_pages":     live["total_pages"],
                "total_amount":    live["total_amount"],
                "status":          "pending" if live["total_amount"] > 0 else "no activity",
            })
            total_revenue += tenant_total_revenue
            this_month += live["total_amount"]

        return {"records": records, "total_revenue": total_revenue, "this_month": this_month}


# ---------------------------------------------------------------------------
# Activity log (audit trail across all companies)
# ---------------------------------------------------------------------------

@router.get("/activity")
async def get_activity(
    current_user: CurrentUser,
    tenant_id: str = "", q: str = "", limit: int = 100,
) -> dict[str, Any]:
    _require_super_admin(current_user)
    async with AsyncSessionLocal() as session:
        # Pre-load lookup maps once instead of querying per-document (avoids N+1)
        tenants  = {t.id: t.name for t in (await session.execute(select(TenantRow))).scalars().all()}
        users    = {u.id: u.name for u in (await session.execute(select(UserRow))).scalars().all()}

        stmt = select(DocumentRow).order_by(DocumentRow.uploaded_at.desc())
        if tenant_id:
            stmt = stmt.where(DocumentRow.tenant_id == tenant_id)
        if q:
            like = f"%{q.lower()}%"
            matching_tenant_ids = [tid for tid, name in tenants.items() if q.lower() in name.lower()]
            stmt = stmt.where(
                func.lower(DocumentRow.document_id).like(like)
                | func.lower(DocumentRow.type).like(like)
                | func.lower(DocumentRow.tcode).like(like)
                | DocumentRow.tenant_id.in_(matching_tenant_ids or [""])
            )

        total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0
        docs = (await session.execute(stmt.limit(limit))).scalars().all()

        result = []
        for d in docs:
            result.append({
                "document_id":   d.document_id,
                "type":          d.type,
                "tcode":         d.tcode,
                "status":        d.status,
                "page_count":    d.page_count,
                "uploaded_by":   users.get(d.uploaded_by, d.uploaded_by),
                "tenant_id":     d.tenant_id,
                "company_name":  tenants.get(d.tenant_id, "—") if d.tenant_id else "—",
                "uploaded_at":   d.uploaded_at.isoformat() if d.uploaded_at else "",
            })
        return {"documents": result, "total": total}
