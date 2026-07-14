"""JWT token management and bcrypt password hashing.

Intentionally stateless — no direct DB access.  All Redis calls are delegated
to redis_client so this service stays testable without infrastructure.
"""
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from jose import ExpiredSignatureError, JWTError, jwt
from passlib.context import CryptContext

from src.config import settings
from src.exceptions import AuthError
from src.schemas.auth import TokenPayload

ACCESS_TOKEN_TYPE = "access"
REFRESH_TOKEN_TYPE = "refresh"

# bcrypt rounds=12 is a good balance of security vs. latency (~300 ms on modern hardware)
_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)


class AuthService:
    # ------------------------------------------------------------------
    # Password helpers
    # ------------------------------------------------------------------

    def hash_password(self, password: str) -> str:
        return _pwd_ctx.hash(password)

    def verify_password(self, plain: str, hashed: str) -> bool:
        return _pwd_ctx.verify(plain, hashed)

    # ------------------------------------------------------------------
    # Token construction
    # ------------------------------------------------------------------

    def _build_token(
        self,
        sub: str,
        email: str,
        role: str,
        token_type: str,
        expire_delta: timedelta,
        tenant_id: str | None = None,
    ) -> tuple[str, str, int]:
        """Return (encoded_jwt, jti, exp_unix_timestamp)."""
        now = datetime.now(UTC)
        jti = str(uuid4())
        exp = int((now + expire_delta).timestamp())
        payload: dict = {
            "sub": sub,
            "email": email,
            "role": role,
            "type": token_type,
            "jti": jti,
            "iat": int(now.timestamp()),
            "exp": exp,
            "tenant_id": tenant_id,
        }
        token = jwt.encode(
            payload,
            settings.JWT_SECRET.get_secret_value(),
            algorithm=settings.JWT_ALGORITHM,
        )
        return token, jti, exp

    async def create_tokens(
        self, user_id: str, email: str, role: str, tenant_id: str | None = None
    ) -> dict[str, str | int]:
        """Create a fresh access + refresh token pair."""
        access_delta  = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        refresh_delta = timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

        access_token, _, _ = self._build_token(
            user_id, email, role, ACCESS_TOKEN_TYPE, access_delta, tenant_id
        )
        refresh_token, _, _ = self._build_token(
            user_id, email, role, REFRESH_TOKEN_TYPE, refresh_delta, tenant_id
        )
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": int(access_delta.total_seconds()),
        }

    # ------------------------------------------------------------------
    # Token verification
    # ------------------------------------------------------------------

    async def verify_token(
        self, token: str, expected_type: str = ACCESS_TOKEN_TYPE
    ) -> TokenPayload:
        try:
            raw = jwt.decode(
                token,
                settings.JWT_SECRET.get_secret_value(),
                algorithms=[settings.JWT_ALGORITHM],
            )
        except ExpiredSignatureError:
            raise AuthError(
                "Token has expired",
                error_code="TOKEN_EXPIRED",
                status_code=401,
            )
        except JWTError:
            raise AuthError(
                "Invalid or malformed token",
                error_code="TOKEN_INVALID",
                status_code=401,
            )

        try:
            payload = TokenPayload(**raw)
        except Exception:
            raise AuthError(
                "Token payload is malformed",
                error_code="TOKEN_INVALID",
                status_code=401,
            )

        if payload.type != expected_type:
            raise AuthError(
                f"Expected {expected_type} token, received {payload.type}",
                error_code="TOKEN_TYPE_MISMATCH",
                status_code=401,
            )
        return payload

    # ------------------------------------------------------------------
    # Token rotation & blacklisting
    # ------------------------------------------------------------------

    async def refresh_access_token(
        self, refresh_token: str
    ) -> dict[str, str | int]:
        """Verify refresh token, rotate it, return new token pair."""
        # Import lazily to avoid module-level circular dependency at import time
        from src.utils.redis_client import get_redis

        payload = await self.verify_token(refresh_token, expected_type=REFRESH_TOKEN_TYPE)

        redis = get_redis()
        if await redis.exists(f"blacklist:{payload.jti}"):
            raise AuthError(
                "Refresh token has been revoked",
                error_code="TOKEN_REVOKED",
                status_code=401,
            )

        # Blacklist the consumed token so it cannot be replayed
        await self.blacklist_token(payload.jti, payload.exp)

        return await self.create_tokens(payload.sub, payload.email, payload.role, payload.tenant_id)

    async def blacklist_token(self, jti: str, expires_at: int) -> None:
        """Store jti in Redis with TTL = remaining token lifetime."""
        from src.utils.redis_client import get_redis

        remaining = expires_at - int(datetime.now(UTC).timestamp())
        if remaining > 0:
            await get_redis().setex(f"blacklist:{jti}", remaining, "1")

    async def is_blacklisted(self, jti: str) -> bool:
        from src.utils.redis_client import get_redis

        return bool(await get_redis().exists(f"blacklist:{jti}"))


# Module-level singleton — import this everywhere
auth_service = AuthService()
