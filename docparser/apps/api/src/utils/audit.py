"""Fire-and-forget audit logging utility."""
import asyncio
from typing import Any

import structlog

log = structlog.get_logger(__name__)

DOCUMENT_UPLOADED = "DOCUMENT_UPLOADED"
OCR_EXTRACTED     = "OCR_EXTRACTED"
SAP_VALIDATED     = "SAP_VALIDATED"
MIRO_POSTED       = "MIRO_POSTED"
MIRO_FAILED       = "MIRO_FAILED"


async def _write_audit(
    document_id: str,
    action: str,
    user_id: str,
    details: dict[str, Any],
    ip_address: str,
) -> None:
    try:
        from src.database import AsyncSessionLocal
        from src.repositories.audit_repository import AuditRepository

        async with AsyncSessionLocal() as session:
            repo = AuditRepository(session)
            await repo.log_action(
                document_id=document_id,
                action=action,
                performed_by=user_id,
                details=details,
                ip_address=ip_address,
            )
            await session.commit()
    except Exception as exc:
        log.warning("audit write failed", document_id=document_id, action=action, error=str(exc))


async def log_action(
    document_id: str,
    action: str,
    user_id: str,
    details: dict[str, Any] | None = None,
    ip_address: str = "",
) -> None:
    asyncio.create_task(
        _write_audit(document_id, action, user_id, details or {}, ip_address)
    )
