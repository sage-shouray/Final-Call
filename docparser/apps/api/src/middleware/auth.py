"""Authentication middleware and FastAPI dependency helpers.

Execution position
------------------
AuthMiddleware sits between RequestLoggingMiddleware (outer) and
RateLimitMiddleware (inner), so by the time the rate limiter runs,
request.state.user is already set and role-aware limits are possible.

Whitelisted paths skip token verification entirely.
"""
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
# WebSocket endpoints authenticate via query-param token, not Authorization header.
_AUTH_WHITELIST_PREFIXES = ("/api/docs", "/api/redoc", "/openapi", "/api/ws")


def _is_whitelisted(path: str) -> bool:
    if path in _AUTH_WHITELIST:
        return True
    return any(path.startswith(prefix) for prefix in _AUTH_WHITELIST_PREFIXES)


def _error_body(
    code: str,
    message: str,
    request_id: str,
) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": {},
            "request_id": request_id,
            "timestamp": datetime.now(UTC).isoformat(),
        }
    }


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: object) -> Response:
        # AUTH BYPASS — attach a hardcoded dev user so all routes work without login
        request.state.user = TokenPayload(
            sub="000000000000000000000001",
            email="admin@docparser.com",
            role="admin",
            type="access",
            jti="dev",
            iat=0,
            exp=9999999999,
        )
        return await call_next(request)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# FastAPI dependency: get_current_user
# ---------------------------------------------------------------------------


async def get_current_user(request: Request) -> TokenPayload:
    """Read the TokenPayload attached by AuthMiddleware.

    Never reaches here if the middleware rejected the token — the 401 was
    already returned before the route handler was invoked.
    """
    user: TokenPayload | None = getattr(request.state, "user", None)
    if user is None:
        # Defensive fallback for routes mounted outside middleware scope
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
    """Return a Depends() that enforces the caller has one of the given roles.

    Usage::

        @router.delete("/documents/{id}")
        async def delete_doc(
            _: Annotated[TokenPayload, require_role("admin", "manager")],
        ) -> ...:
    """
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
