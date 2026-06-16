"""Global exception handlers — converts every error into a consistent JSON body.

Response envelope:
    {
      "error": {
        "code":       "SNAKE_CASE_STRING",
        "message":    "Human-readable description",
        "details":    {...},          // optional field-level errors
        "request_id": "uuid",
        "timestamp":  "ISO-8601"
      }
    }

Stack traces are NEVER included in responses; 5xx errors are forwarded to Sentry.
"""
from datetime import UTC, datetime
from typing import Any

import sentry_sdk
import structlog
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError as PydanticValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.exceptions import DocParserException, RateLimitError

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _error_body(
    code: str,
    message: str,
    request_id: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
            "request_id": request_id,
            "timestamp": datetime.now(UTC).isoformat(),
        }
    }


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", ""))


# ---------------------------------------------------------------------------
# Handler functions
# ---------------------------------------------------------------------------

async def _handle_docparser_exception(
    request: Request, exc: DocParserException
) -> JSONResponse:
    headers: dict[str, str] = {}

    if exc.status_code >= 500:
        log.error(
            "internal error",
            error_code=exc.error_code,
            message=exc.message,
            path=request.url.path,
        )
        sentry_sdk.capture_exception(exc)

    if isinstance(exc, RateLimitError):
        headers["Retry-After"] = str(exc.retry_after)

    return JSONResponse(
        status_code=exc.status_code,
        content=_error_body(exc.error_code, exc.message, _request_id(request), exc.details),
        headers=headers,
    )


async def _handle_http_exception(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    code_map = {
        400: "BAD_REQUEST",
        401: "AUTHENTICATION_FAILED",
        403: "PERMISSION_DENIED",
        404: "NOT_FOUND",
        405: "METHOD_NOT_ALLOWED",
        409: "CONFLICT",
        422: "UNPROCESSABLE_ENTITY",
        429: "RATE_LIMIT_EXCEEDED",
        500: "INTERNAL_ERROR",
        502: "BAD_GATEWAY",
        503: "SERVICE_UNAVAILABLE",
    }
    code = code_map.get(exc.status_code, "HTTP_ERROR")
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_body(code, str(exc.detail), _request_id(request)),
    )


async def _handle_request_validation_error(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Converts FastAPI's 422 pydantic validation errors into our envelope."""
    details: dict[str, list[str]] = {}
    for err in exc.errors():
        field = ".".join(str(loc) for loc in err["loc"] if loc != "body")
        details.setdefault(field, []).append(err["msg"])

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=_error_body(
            "VALIDATION_ERROR",
            "Request validation failed",
            _request_id(request),
            details,
        ),
    )


async def _handle_pydantic_validation_error(
    request: Request, exc: PydanticValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=_error_body(
            "VALIDATION_ERROR",
            "Data validation failed",
            _request_id(request),
            {"raw": str(exc)},
        ),
    )


async def _handle_unhandled_exception(
    request: Request, exc: Exception
) -> JSONResponse:
    log.exception(
        "unhandled exception",
        path=request.url.path,
        method=request.method,
        exc_type=type(exc).__name__,
    )
    sentry_sdk.capture_exception(exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=_error_body(
            "INTERNAL_ERROR",
            "An unexpected error occurred",
            _request_id(request),
        ),
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def setup_exception_handlers(app: FastAPI) -> None:
    """Register all handlers with the FastAPI app."""
    app.add_exception_handler(DocParserException, _handle_docparser_exception)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, _handle_request_validation_error)  # type: ignore[arg-type]
    app.add_exception_handler(PydanticValidationError, _handle_pydantic_validation_error)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, _handle_unhandled_exception)  # type: ignore[arg-type]
