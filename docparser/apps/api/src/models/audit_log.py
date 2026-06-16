"""AuditLog model — maps to the 'audit_logs' MongoDB collection."""
from datetime import datetime
from typing import Any

from pydantic import Field

from src.models.base import MongoModel, _utcnow


class AuditLog(MongoModel):
    """Immutable audit trail entry. Never updated after creation."""

    document_id: str
    action: str = Field(..., description="E.g. 'status_change', 'upload', 'post_miro'")
    performed_by: str
    timestamp: datetime = Field(default_factory=_utcnow)
    details: dict[str, Any] = Field(default_factory=dict)
    ip_address: str = ""
