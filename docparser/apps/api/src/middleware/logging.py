"""RequestLoggingMiddleware — structured per-request logging via structlog.

Every request gets a UUID request_id that:
  1. Is read from X-Request-ID header (client-supplied) if present.
  2. Is generated fresh if absent.
  3. Is echoed back in the X-Request-ID response header.
  4. Is bound into structlog's contextvars so every downstream log line
     automatically carries it without manual threading.

Request bodies are never logged.
"""
import time
from uuid import uuid4

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from structlog.contextvars import bind_contextvars, clear_contextvars

log = structlog.get_logger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: object) -> Response:
        # Clear any context leaked from a previous request on this worker
        clear_contextvars()

        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        bind_contextvars(request_id=request_id)

        # Make request_id available to other middleware and route handlers
        request.state.request_id = request_id

        start = time.perf_counter()
        response: Response = await call_next(request)  # type: ignore[arg-type, assignment]
        duration_ms = round((time.perf_counter() - start) * 1000, 2)

        # Echo request_id so API consumers can correlate client-side errors
        response.headers["X-Request-ID"] = request_id

        # Derive user_id from state if AuthMiddleware has run (it runs after us
        # in the chain so this will normally be None here; we log it anyway for
        # response-phase enrichment when middleware order is adjusted in future).
        user_id: str | None = None
        user = getattr(request.state, "user", None)
        if user is not None:
            user_id = getattr(user, "sub", None)

        log.info(
            "request",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
            user_id=user_id,
            request_id=request_id,
        )

        clear_contextvars()
        return response
