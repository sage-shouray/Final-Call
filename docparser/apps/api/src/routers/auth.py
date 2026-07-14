"""Authentication endpoints."""
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

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


@router.post("/login", response_model=LoginResponse, summary="Obtain access and refresh tokens")
async def login(body: LoginRequest, request: Request) -> LoginResponse:
    from src.database import AsyncSessionLocal
    async with AsyncSessionLocal() as session:
        user_repo = UserRepository(session)
        user_doc = await user_repo.find_by_email(body.email)

    dummy_hash = "$2b$12$WTUxbMsgJQi9tRpL2K5oOOlwDriU8Cb9HmJJJFriHJCTe0L5w6bOi"
    candidate_hash = user_doc["hashed_password"] if user_doc else dummy_hash

    password_ok = auth_service.verify_password(body.password, candidate_hash)

    if not user_doc or not password_ok:
        raise AuthError("Invalid email or password", error_code="INVALID_CREDENTIALS", status_code=401)

    if not user_doc.get("is_active", True):
        raise AuthError("This account has been deactivated", error_code="ACCOUNT_INACTIVE", status_code=401)

    user_id = str(user_doc["id"])
    tokens = await auth_service.create_tokens(
        user_id, user_doc["email"], user_doc["role"],
        user_doc.get("tenant_id"),
    )

    async with AsyncSessionLocal() as session:
        await UserRepository(session).update_last_login(user_id)
        await session.commit()

    log.info("user logged in", email=user_doc["email"], role=user_doc["role"])

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
