"""Pydantic v2 request/response schemas for the auth domain."""
from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class UserPublic(BaseModel):
    """Safe user representation — no hashed_password field."""

    id: str
    email: str
    name: str
    role: str
    is_active: bool


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds until access token expires
    user: UserPublic


class RefreshResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class TokenPayload(BaseModel):
    """Decoded JWT payload — attached to request.state.user by AuthMiddleware."""

    sub: str    # hex ObjectId of the user
    email: str
    role: str
    type: str   # "access" | "refresh"
    jti: str    # JWT ID used for blacklisting
    iat: int    # issued-at unix timestamp
    exp: int    # expiry unix timestamp
