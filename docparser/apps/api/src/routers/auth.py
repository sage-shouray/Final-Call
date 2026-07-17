"""Authentication endpoints."""
from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import func, select, text

from src.exceptions import AuthError, NotFoundError
from src.middleware.auth import CurrentUser
from src.repositories.user_repository import UserRepository
from src.schemas.auth import (
    LoginRequest,
    LoginResponse,
    LogoutRequest,
    RefreshRequest,
    RefreshResponse,
    UserPublic,
)
from src.services.auth_service import REFRESH_TOKEN_TYPE, auth_service

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/auth", tags=["Auth"])


_BF_MAX_ATTEMPTS = 5      # max failed attempts before lockout
_BF_LOCKOUT_SECS = 900    # 15-minute ban


async def _check_brute_force(ip: str) -> None:
    """Raise 429 if this IP has too many recent failed login attempts."""
    try:
        from src.utils.redis_client import get_redis
        redis = get_redis()
        count = await redis.get(f"bf:login:{ip}")
        if count and int(count) >= _BF_MAX_ATTEMPTS:
            raise HTTPException(
                status_code=429,
                detail="Too many failed login attempts. Try again in 15 minutes.",
                headers={"Retry-After": str(_BF_LOCKOUT_SECS)},
            )
    except HTTPException:
        raise
    except Exception:
        pass  # Redis unavailable — allow through


async def _record_failed_login(ip: str) -> None:
    try:
        from src.utils.redis_client import get_redis
        redis = get_redis()
        key = f"bf:login:{ip}"
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, _BF_LOCKOUT_SECS)
    except Exception:
        pass


async def _clear_brute_force(ip: str) -> None:
    try:
        from src.utils.redis_client import get_redis
        await get_redis().delete(f"bf:login:{ip}")
    except Exception:
        pass


async def _write_audit(
    *,
    action: str,
    performed_by: str,
    ip_address: str,
    document_id: str | None = None,
    details: dict | None = None,
) -> None:
    try:
        from src.database import AsyncSessionLocal
        from src.models.audit_log import AuditLogRow
        async with AsyncSessionLocal() as _session:
            _session.add(AuditLogRow(
                document_id=document_id,
                action=action,
                performed_by=performed_by,
                ip_address=ip_address,
                details=details or {},
            ))
            await _session.commit()
    except Exception as _exc:
        log.warning("audit log write failed", error=str(_exc))


@router.post("/login", response_model=LoginResponse, summary="Obtain access and refresh tokens")
async def login(body: LoginRequest, request: Request) -> LoginResponse:
    ip = request.client.host if request.client else "unknown"
    await _check_brute_force(ip)

    from src.database import AsyncSessionLocal
    async with AsyncSessionLocal() as session:
        user_repo = UserRepository(session)
        user_doc = await user_repo.find_by_email(body.email)

    dummy_hash = "$2b$12$WTUxbMsgJQi9tRpL2K5oOOlwDriU8Cb9HmJJJFriHJCTe0L5w6bOi"
    candidate_hash = user_doc["hashed_password"] if user_doc else dummy_hash

    password_ok = auth_service.verify_password(body.password, candidate_hash)

    if not user_doc or not password_ok:
        await _record_failed_login(ip)
        raise AuthError("Invalid email or password", error_code="INVALID_CREDENTIALS", status_code=401)

    if not user_doc.get("is_active", True):
        raise AuthError("This account has been deactivated", error_code="ACCOUNT_INACTIVE", status_code=401)

    await _clear_brute_force(ip)

    user_id = str(user_doc["id"])
    tokens = await auth_service.create_tokens(
        user_id, user_doc["email"], user_doc["role"],
        user_doc.get("tenant_id"),
    )

    async with AsyncSessionLocal() as session:
        await UserRepository(session).update_last_login(user_id)
        await session.commit()

    log.info("user logged in", email=user_doc["email"], role=user_doc["role"])
    import asyncio as _asyncio
    _asyncio.create_task(_write_audit(
        action="user.login",
        performed_by=user_id,
        ip_address=ip,
        details={"email": user_doc["email"], "role": user_doc["role"]},
    ))

    return LoginResponse(
        **tokens,
        user=UserPublic(
            id=user_id,
            email=user_doc["email"],
            name=user_doc["name"],
            role=user_doc["role"],
            is_active=user_doc["is_active"],
        ),
    )


@router.post("/refresh", response_model=RefreshResponse, summary="Rotate refresh token")
async def refresh(body: RefreshRequest) -> RefreshResponse:
    tokens = await auth_service.refresh_access_token(body.refresh_token)
    return RefreshResponse(**tokens)


@router.post("/logout", status_code=204, summary="Invalidate refresh token")
async def logout(body: LogoutRequest) -> None:
    try:
        payload = await auth_service.verify_token(body.refresh_token, expected_type=REFRESH_TOKEN_TYPE)
        await auth_service.blacklist_token(payload.jti, payload.exp)
        log.info("user logged out", user_id=payload.sub)
    except AuthError:
        pass


@router.get("/me", response_model=UserPublic, summary="Return authenticated user profile")
async def me(current_user: CurrentUser) -> UserPublic:
    from src.database import AsyncSessionLocal
    async with AsyncSessionLocal() as session:
        user_doc = await UserRepository(session).find_by_id(current_user.sub)

    if not user_doc:
        raise NotFoundError("User not found", error_code="USER_NOT_FOUND")

    return UserPublic(
        id=str(user_doc["id"]),
        email=user_doc["email"],
        name=user_doc["name"],
        role=user_doc["role"],
        is_active=user_doc["is_active"],
    )


@router.put("/me/password", summary="Change own password")
async def change_password(body: dict[str, Any], current_user: CurrentUser) -> dict[str, str]:
    old_pw  = (body.get("old_password") or "").strip()
    new_pw  = (body.get("new_password") or "").strip()
    if not old_pw or not new_pw:
        raise HTTPException(status_code=422, detail="old_password and new_password are required.")
    if len(new_pw) < 8:
        raise HTTPException(status_code=422, detail="New password must be at least 8 characters.")

    from src.database import AsyncSessionLocal
    from src.models.user import UserRow
    async with AsyncSessionLocal() as session:
        user = (await session.execute(select(UserRow).where(UserRow.id == current_user.sub))).scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="User not found.")
        if not auth_service.verify_password(old_pw, user.hashed_password):
            raise HTTPException(status_code=400, detail="Current password is incorrect.")
        user.hashed_password = auth_service.hash_password(new_pw)
        await session.commit()
    return {"message": "Password updated successfully."}


# ---------------------------------------------------------------------------
# Manager — user management within own company
# Managers can list, create, and toggle users only in their own tenant.
# ---------------------------------------------------------------------------

def _require_manager(user: CurrentUser) -> None:
    if user.role not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Manager access required.")

def _require_own_tenant(user: CurrentUser) -> str:
    """Returns tenant_id or raises if user has no tenant (super-admin has none)."""
    tid = getattr(user, "tenant_id", None)
    if not tid:
        raise HTTPException(status_code=400, detail="No tenant associated with this account.")
    return tid


@router.get("/team", summary="Manager: list users in own company")
async def list_team(current_user: CurrentUser) -> list[dict[str, Any]]:
    _require_manager(current_user)
    from src.database import AsyncSessionLocal
    from src.models.user import UserRow
    from sqlalchemy import func
    from src.models.document import DocumentRow

    # super-admin can't call this (they use /admin/companies/:id/users)
    tenant_id = _require_own_tenant(current_user)

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


@router.post("/team", status_code=201, summary="Manager: add user to own company")
async def add_team_member(body: dict[str, Any], current_user: CurrentUser) -> dict[str, Any]:
    _require_manager(current_user)
    tenant_id = _require_own_tenant(current_user)

    email    = (body.get("email") or "").strip().lower()
    name     = (body.get("name") or "").strip()
    role     = body.get("role", "operator")
    password = body.get("password", "")

    if not email or not name or not password:
        raise HTTPException(status_code=422, detail="email, name, and password are required.")
    if len(password) < 8:
        raise HTTPException(status_code=422, detail="Password must be at least 8 characters.")
    # managers cannot create other managers or admins
    if current_user.role == "manager" and role not in ("operator",):
        raise HTTPException(status_code=403, detail="Managers can only create operator accounts.")

    from src.database import AsyncSessionLocal
    from src.models.user import UserRow
    async with AsyncSessionLocal() as session:
        existing = (await session.execute(select(UserRow).where(UserRow.email == email))).scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=409, detail="Email already in use.")
        user = UserRow(
            email=email, name=name, role=role,
            hashed_password=auth_service.hash_password(password),
            tenant_id=tenant_id, is_active=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        log.info("team member added", by=current_user.sub, email=email, tenant=tenant_id)
        import asyncio as _asyncio
        _asyncio.create_task(_write_audit(
            action="user.created",
            performed_by=current_user.sub,
            ip_address="",
            details={"email": email, "role": role, "tenant_id": tenant_id},
        ))
        return user.to_dict()


@router.put("/team/{user_id}", summary="Manager: update user in own company")
async def update_team_member(user_id: str, body: dict[str, Any], current_user: CurrentUser) -> dict[str, Any]:
    _require_manager(current_user)
    tenant_id = _require_own_tenant(current_user)

    from src.database import AsyncSessionLocal
    from src.models.user import UserRow
    async with AsyncSessionLocal() as session:
        user = (await session.execute(
            select(UserRow).where(UserRow.id == user_id, UserRow.tenant_id == tenant_id)
        )).scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="User not found in your company.")
        # managers cannot promote to manager/admin
        if "role" in body and current_user.role == "manager" and body["role"] not in ("operator",):
            raise HTTPException(status_code=403, detail="Managers cannot assign manager or admin roles.")
        for field in ("name", "role"):
            if field in body:
                setattr(user, field, body[field])
        if "is_active" in body:
            user.is_active = bool(body["is_active"])
        # optional password reset by manager
        if body.get("new_password"):
            if len(body["new_password"]) < 8:
                raise HTTPException(status_code=422, detail="Password must be at least 8 characters.")
            user.hashed_password = auth_service.hash_password(body["new_password"])
        await session.commit()
        await session.refresh(user)
        return user.to_dict()


# ---------------------------------------------------------------------------
# Manager — billing within own company
# Shows documents processed and cost owed for the current billing period.
# ---------------------------------------------------------------------------

_MONTH_NAMES = [
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


@router.get("/billing", summary="Manager: billing summary for own company")
async def get_own_billing(current_user: CurrentUser) -> dict[str, Any]:
    _require_manager(current_user)
    tenant_id = _require_own_tenant(current_user)
    now = datetime.now(UTC)

    from src.database import AsyncSessionLocal
    from src.models.tenant import BillingRecordRow, PricingConfigRow

    async with AsyncSessionLocal() as session:
        rows = (await session.execute(text("""
            SELECT d.tcode, COUNT(*) as doc_count, COALESCE(SUM(d.page_count), 0) as page_count
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
        total_docs = 0
        total_pages = 0
        for row in rows:
            tcode, doc_count, page_count = row[0], row[1], row[2]
            p      = pricing.get(tcode)
            price  = float(p.price_per_document) if p else 0.0
            amount = doc_count * price
            total       += amount
            total_docs  += doc_count
            total_pages += int(page_count)
            line_items.append({
                "tcode":      tcode,
                "label":      p.label if p else tcode,
                "doc_count":  doc_count,
                "price_each": price,
                "amount":     amount,
            })

        history = (await session.execute(
            select(BillingRecordRow).where(BillingRecordRow.tenant_id == tenant_id)
            .order_by(BillingRecordRow.period_year.desc(), BillingRecordRow.period_month.desc())
        )).scalars().all()

        return {
            "period_month":     now.month,
            "period_year":      now.year,
            "period_label":     f"{_MONTH_NAMES[now.month]} {now.year}",
            "line_items":       line_items,
            "total_documents":  total_docs,
            "total_pages":      total_pages,
            "total_due":        total,
            "history":          [r.to_dict() for r in history],
        }
