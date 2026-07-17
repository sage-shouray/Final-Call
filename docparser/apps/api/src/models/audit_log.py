"""AuditLog model — maps to the 'audit_logs' PostgreSQL table."""
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, _utcnow


class AuditLogRow(Base):
    """Immutable audit trail entry. Never updated after creation."""

    __tablename__ = "audit_logs"

    id:           Mapped[str]  = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    document_id:  Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    action:       Mapped[str]  = mapped_column(String, nullable=False)
    performed_by: Mapped[str]  = mapped_column(String, nullable=False)
    timestamp:    Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now(), index=True
    )
    details:      Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    ip_address:   Mapped[str]  = mapped_column(String, nullable=False, default="")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id":           self.id,
            "document_id":  self.document_id,
            "action":       self.action,
            "performed_by": self.performed_by,
            "timestamp":    self.timestamp,
            "details":      self.details or {},
            "ip_address":   self.ip_address,
        }


# Backwards-compat alias
AuditLog = AuditLogRow
