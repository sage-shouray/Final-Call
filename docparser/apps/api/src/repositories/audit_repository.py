"""AuditRepository — append-only log of every significant action."""
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.audit_log import AuditLogRow
from src.repositories.base import BaseRepository

log = structlog.get_logger(__name__)


class AuditRepository(BaseRepository[AuditLogRow]):
    _model = AuditLogRow

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def log_action(
        self,
        document_id: str,
        action: str,
        performed_by: str,
        details: dict[str, Any] | None = None,
        ip_address: str = "",
    ) -> str:
        """Append an audit entry and return its inserted id."""
        entry: dict[str, Any] = {
            "document_id":  document_id,
            "action":       action,
            "performed_by": performed_by,
            "timestamp":    datetime.now(UTC),
            "details":      details or {},
            "ip_address":   ip_address,
        }
        inserted_id = await self.create(entry)
        log.info("audit logged", document_id=document_id, action=action, by=performed_by)
        return inserted_id

    async def get_document_history(
        self, document_id: str, *, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Return all audit entries for a document, newest first."""
        return await self.list(
            filter={"document_id": document_id},
            sort=[("timestamp", -1)],
            limit=limit,
        )
