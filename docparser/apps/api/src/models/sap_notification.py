"""Inbound SAP notifications — SAP posts to us when stock clears quality hold.

Sangam's workflow needed a way for SAP to tell us "this PO's stock moved from
blocked to unrestricted, go ahead and park the invoice" — originally planned as
an email to the shared mailbox, replaced with a direct API call once SAP's own
side could be coded to consume it instead of sending mail.

Deliberately not handled inline on the POST: the request is just recorded here,
and a separate scheduler (sap_notification_worker.py) picks up unprocessed rows
on its own cadence — the same decoupled shape the mail poller already uses, and
for the same reason: a slow or failing downstream step (finding the document,
calling MIRO Park) must not hold the HTTP connection SAP is waiting on open.
"""
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, _utcnow


class SapNotificationRow(Base):
    __tablename__ = "sap_notifications"

    id:            Mapped[str]  = mapped_column(String, primary_key=True)
    po_number:     Mapped[str]  = mapped_column(String, nullable=False, default="", index=True)
    status:        Mapped[str]  = mapped_column(String, nullable=False, default="")
    message:       Mapped[str]  = mapped_column(Text, nullable=False, default="")
    raw_payload:   Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    processed:     Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    attempts:      Mapped[int]  = mapped_column(Integer, nullable=False, default=0)
    document_id:   Mapped[str]  = mapped_column(String, nullable=False, default="")
    result:        Mapped[str]  = mapped_column(Text, nullable=False, default="")
    processed_at:  Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id":           self.id,
            "po_number":    self.po_number,
            "status":       self.status,
            "message":      self.message,
            "processed":    self.processed,
            "attempts":     self.attempts,
            "document_id":  self.document_id,
            "result":       self.result,
            "received_at":  self.received_at,
            "processed_at": self.processed_at,
        }
