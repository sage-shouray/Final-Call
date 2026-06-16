"""Fire-and-forget audit logging utility.

Callers schedule audit writes without awaiting them so the request path
is never blocked by a secondary write.

Usage (in a FastAPI route or async worker):
    asyncio.create_task(log_action(document_id, "MIRO_POSTED", user_id, details))
"""
import asyncio
from typing import Any

import structlog

log = structlog.get_logger(__name__)

# Action constants — keep in sync with frontend event types
DOCUMENT_UPLOADED = "DOCUMENT_UPLOADED"
OCR_EXTRACTED = "OCR_EXTRACTED"
SAP_VALIDATED = "SAP_VALIDATED"
MIRO_POSTED = "MIRO_POSTED"
MIRO_FAILED = "MIRO_FAILED"


async def _write_audit(
    document_id: str,
    action: str,
    user_id: str,
    details: dict[str, Any],
    ip_address: str,
) -> None:
    """Actual DB write — runs as a background task."""
    try:
        from src.database import get_database
        from src.repositories.audit_repository import AuditRepository

        db = get_database()
        repo = AuditRepository(db)
        await repo.log_action(
            document_id=document_id,
            action=action,
            performed_by=user_id,
            details=details,
            ip_address=ip_address,
        )
    except Exception as exc:
        log.warning(
            "audit write failed",
            document_id=document_id,
            action=action,
            error=str(exc),
        )


async def log_action(
    document_id: str,
    action: str,
    user_id: str,
    details: dict[str, Any] | None = None,
    ip_address: str = "",
) -> None:
    """Schedule an audit write as a fire-and-forget background task.

    The caller does NOT need to await the result:
        asyncio.create_task(log_action(...))

    Or from inside an async function where the event loop is running:
        await log_action(...)   ← returns immediately after scheduling
    """
    asyncio.create_task(
        _write_audit(document_id, action, user_id, details or {}, ip_address)
    )
