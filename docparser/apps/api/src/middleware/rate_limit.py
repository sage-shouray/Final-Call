"""RateLimitMiddleware — per-user (or per-IP) sliding-window rate limiter.

Strategy
--------
* Key scheme: ``rate_limit:{user_id}:{minute_bucket}``
  where ``minute_bucket = int(unix_time // 60)``.
* Each key is set with INCR + TTL=60 s (atomic via Redis INCR / EXPIRE).
* Limits:
    - admin role      → RATE_LIMIT_ADMIN  req / min  (default 300)
    - authenticated   → RATE_LIMIT_DEFAULT req / min (default 100)
    - unauthenticated → RATE_LIMIT_ANON    req / min (default 60, by IP)
* If Redis is unavailable the request is allowed through — we prefer
  availability over correctness for a transient infra outage.
* Whitelisted paths bypass the limiter entirely.
"""
import math
import time
from datetime import UTC, datetime

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from src.config import settings

log = structlog.get_logger(__name__)

# Paths that are never rate-limited (health probes, auth handshake)
# NOTE: /api/auth/login is NOT whitelisted — brute-force protection is
# handled in the login endpoint itself (per-IP lockout via Redis).
_WHITELIST = frozenset({
    "/api/health",
    "/api/health/ready",
    "/api/auth/refresh",
})

# Prefixes exempt from rate limiting (WebSocket upgrade requests)
_WHITELIST_PREFIXES = ("/api/ws",)

_RATE_LIMIT_ANON = 60  # req / min for unauthenticated requests


def _error_body(request_id: str, retry_after: int) -> dict:
    return {
        "error": {
            "code": "RATE_LIMIT_EXCEEDED",
            "message": "Too many requests — please slow down",
            "details": {"retry_after_seconds": retry_after},
            "request_id": request_id,
            "timestamp": datetime.now(UTC).isoformat(),
        }
    }


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: object) -> Response:
        path = request.url.path
        if path in _WHITELIST or any(path.startswith(p) for p in _WHITELIST_PREFIXES):
            return await call_next(request)  # type: ignore[arg-type]

        # AuthMiddleware runs before us, so request.state.user is populated
        user = getattr(request.state, "user", None)
        request_id = getattr(request.state, "request_id", "")

        now = int(time.time())
        minute_bucket = now // 60
        retry_after = 60 - (now % 60)

        if user is not None:
            role = getattr(user, "role", "operator")
            limit = (
                settings.RATE_LIMIT_ADMIN
                if role == "admin"
                else settings.RATE_LIMIT_DEFAULT
            )
            key = f"rate_limit:{user.sub}:{minute_bucket}"
        else:
            limit = _RATE_LIMIT_ANON
            ip = (request.client.host if request.client else "unknown")
            key = f"rate_limit:ip:{ip}:{minute_bucket}"

        try:
            from src.utils.redis_client import get_redis  # lazy to avoid circular import at module level
            redis = get_redis()

            # Atomic increment; set expiry only on first request of the window
            count = await redis.incr(key)
            if count == 1:
                await redis.expire(key, 60)

            if count > limit:
                log.warning(
                    "rate limit exceeded",
                    key=key,
                    count=count,
                    limit=limit,
                )
                return JSONResponse(
                    status_code=429,
                    content=_error_body(request_id, retry_after),
                    headers={
                        "Retry-After": str(retry_after),
                        "X-RateLimit-Limit": str(limit),
                        "X-RateLimit-Remaining": "0",
                        "X-RateLimit-Reset": str((minute_bucket + 1) * 60),
                    },
                )

            response: Response = await call_next(request)  # type: ignore[arg-type, assignment]
            remaining = max(0, limit - count)
            response.headers["X-RateLimit-Limit"] = str(limit)
            response.headers["X-RateLimit-Remaining"] = str(remaining)
            response.headers["X-RateLimit-Reset"] = str((minute_bucket + 1) * 60)
            return response

        except Exception as exc:
            # Never block requests because Redis is unavailable
            if not isinstance(exc, Exception.__class__) or "rate" not in str(exc).lower():
                log.warning("rate limiter Redis error — passing through", error=str(exc))
            return await call_next(request)  # type: ignore[arg-type]
