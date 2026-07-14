"""Authentication middleware and FastAPI dependency helpers.

Execution position
------------------
AuthMiddleware sits between RequestLoggingMiddleware (outer) and
RateLimitMiddleware (inner), so by the time the rate limiter runs,
request.state.user is already set and role-aware limits are possible.

Whitelisted paths skip token verification entirely.
"""
import json
from datetime import UTC, datetime
from typing import Annotated, Any

import structlog
from fastapi import Depends, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from src.exceptions import AuthError, ForbiddenError
from src.schemas.auth import TokenPayload

log = structlog.get_logger(__name__)

# Paths that do not require a valid JWT
_AUTH_WHITELIST = frozenset({
    "/api/auth/login",
    "/api/auth/refresh",
    "/api/health",
    "/api/health/ready",
    "/api/docs",
    "/api/redoc",
    "/api/openapi.json",
})

# Prefixes that are always public (Swagger UI assets, WebSocket endpoints)
_AUTH_WHITELIST_PREFIXES = ("/api/docs", "/api/redoc", "/openapi", "/api/ws")


def _is_whitelisted(path: str) -> bool:
    if path in _AUTH_WHITELIST:
        return True
    return any(path.startswith(prefix) for prefix in _AUTH_WHITELIST_PREFIXES)


def _json_error(code: str, message: str, request_id: str, status: int) -> Response:
    body = json.dumps({
        "error": {
            "code": code,
            "message": message,
            "details": {},
            "request_id": request_id,
            "timestamp": datetime.now(UTC).isoformat(),
        }
    })
    return Response(content=body, status_code=status, media_type="application/json")


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: object) -> Response:
        if _is_whitelisted(request.url.path):
            return await call_next(request)  # type: ignore[arg-type]

        request_id = getattr(request.state, "request_id", "")

        auth_header: str = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return _json_error(
                "NOT_AUTHENTICATED",
                "Authorization header missing or malformed.",
                request_id, 401,
            )

        token = auth_header[7:].strip()

        from src.services.auth_service import auth_service
        try:
            payload = await auth_service.verify_token(token, expected_type="access")
        except AuthError as exc:
            return _json_error(exc.error_code, exc.message, request_id, exc.status_code)
        except Exception:
            return _json_error("TOKEN_INVALID", "Invalid token.", request_id, 401)

        request.state.user = payload
        return await call_next(request)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# FastAPI dependency: get_current_user
# ---------------------------------------------------------------------------

async def get_current_user(request: Request) -> TokenPayload:
    """Read the TokenPayload attached by AuthMiddleware."""
    user: TokenPayload | None = getattr(request.state, "user", None)
    if user is None:
        raise AuthError(
            "Not authenticated",
            error_code="NOT_AUTHENTICATED",
            status_code=401,
        )
    return user


CurrentUser = Annotated[TokenPayload, Depends(get_current_user)]


# ---------------------------------------------------------------------------
# FastAPI dependency factory: require_role
# ---------------------------------------------------------------------------

def require_role(*roles: str) -> Any:
    """Return a Depends() that enforces the caller has one of the given roles."""
    async def _checker(
        current_user: Annotated[TokenPayload, Depends(get_current_user)],
    ) -> TokenPayload:
        if current_user.role not in roles:
            raise ForbiddenError(
                f"Role '{current_user.role}' is not permitted. Required: {list(roles)}",
                error_code="PERMISSION_DENIED",
                status_code=403,
            )
        return current_user

    return Depends(_checker)
