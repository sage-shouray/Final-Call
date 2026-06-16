"""Custom exception hierarchy for DocParser.

All business errors inherit from DocParserException so the global handler
can catch them with a single except clause and produce a consistent JSON body.
"""
from typing import Any


class DocParserException(Exception):
    """Base for every DocParser business error."""

    status_code: int = 500
    error_code: str = "INTERNAL_ERROR"

    def __init__(
        self,
        message: str,
        *,
        error_code: str | None = None,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if error_code is not None:
            self.error_code = error_code
        if status_code is not None:
            self.status_code = status_code
        self.details: dict[str, Any] = details or {}


class AuthError(DocParserException):
    status_code = 401
    error_code = "AUTHENTICATION_FAILED"


class ForbiddenError(DocParserException):
    status_code = 403
    error_code = "PERMISSION_DENIED"


class NotFoundError(DocParserException):
    status_code = 404
    error_code = "NOT_FOUND"


class ValidationError(DocParserException):
    """Domain-level validation error (distinct from Pydantic's ValidationError)."""

    status_code = 422
    error_code = "VALIDATION_ERROR"


class ConflictError(DocParserException):
    status_code = 409
    error_code = "CONFLICT"


class SAPConnectionError(DocParserException):
    status_code = 502
    error_code = "SAP_CONNECTION_FAILED"


class SAPCircuitOpenError(SAPConnectionError):
    """Raised when the SAP circuit breaker is in the OPEN state."""

    status_code = 503
    error_code = "SAP_CIRCUIT_OPEN"

    def __init__(
        self,
        message: str = "SAP circuit breaker is open",
        *,
        retry_after: int = 60,
        **kwargs: Any,
    ) -> None:
        super().__init__(message, **kwargs)
        self.retry_after = retry_after


class OCRError(DocParserException):
    status_code = 422
    error_code = "OCR_EXTRACTION_FAILED"


class RateLimitError(DocParserException):
    status_code = 429
    error_code = "RATE_LIMIT_EXCEEDED"

    def __init__(
        self,
        message: str = "Too many requests — rate limit exceeded",
        *,
        retry_after: int = 60,
        **kwargs: Any,
    ) -> None:
        super().__init__(message, **kwargs)
        self.retry_after = retry_after
