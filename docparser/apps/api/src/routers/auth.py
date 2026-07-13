"""Authentication endpoints."""
import structlog
from fastapi import APIRouter, Request

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
    tokens = await auth_service.create_tokens(user_id, user_doc["email"], user_doc["role"])

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
