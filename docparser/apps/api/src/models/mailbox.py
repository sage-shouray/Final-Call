"""Per-tenant invoice mailbox configuration.

Each customer points the tool at their own mailbox — invoices@theircompany.com —
and that mailbox is what identifies them. The tenant is never read from the
message: To, From and Subject are all attacker-controlled, so the only
trustworthy signal is which authenticated mailbox the message was found in.

Credentials are stored encrypted rather than in plain text, because this table
holds N customers' mail passwords and OAuth secrets.
"""
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, _utcnow


class MailProvider(StrEnum):
    """How we reach the mailbox.

    MICROSOFT_GRAPH is the one to prefer on Office 365: Microsoft disabled Basic
    Authentication for IMAP in Exchange Online, so a username and password will
    simply be refused there.
    """
    MICROSOFT_GRAPH = "microsoft_graph"
    IMAP            = "imap"
    GMAIL_IMAP      = "gmail_imap"


class MailboxRow(Base):
    __tablename__ = "tenant_mailboxes"

    id:              Mapped[str]  = mapped_column(String, primary_key=True)
    tenant_id:       Mapped[str]  = mapped_column(String, nullable=False, index=True)
    provider:        Mapped[str]  = mapped_column(String, nullable=False, default=MailProvider.IMAP.value)
    label:           Mapped[str]  = mapped_column(String, nullable=False, default="")
    address:         Mapped[str]  = mapped_column(String, nullable=False, default="")

    # Encrypted blob — never returned by the API, only written.
    credentials_enc: Mapped[str]  = mapped_column(Text, nullable=False, default="")

    folder:          Mapped[str]  = mapped_column(String, nullable=False, default="INBOX")
    poll_interval_s: Mapped[int]  = mapped_column(Integer, nullable=False, default=60)
    enabled:         Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Mail from an address not on this list is still ingested, but never posted
    # unattended. Empty means nothing is pre-trusted.
    sender_allowlist: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    # Auto-posting is decided per mailbox as well as globally: a customer may be
    # happy to automate uploads by their own staff while wanting every emailed
    # invoice reviewed. Both must be true for an emailed document to post itself.
    auto_post_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Health, surfaced in admin so a support person can see "secret expired"
    # without reading logs.
    last_polled_at:       Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at:      Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error:           Mapped[str]  = mapped_column(Text, nullable=False, default="")
    consecutive_failures: Mapped[int]  = mapped_column(Integer, nullable=False, default=0)
    messages_seen:        Mapped[int]  = mapped_column(Integer, nullable=False, default=0)
    documents_ingested:   Mapped[int]  = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )

    def to_dict(self, *, include_secrets: bool = False) -> dict[str, Any]:
        """Serialise for the API.

        Credentials are omitted by default: an admin UI needs to know a mailbox
        is configured, never what the secret is.
        """
        data: dict[str, Any] = {
            "id":                 self.id,
            "tenant_id":          self.tenant_id,
            "provider":           self.provider,
            "label":              self.label,
            "address":            self.address,
            "folder":             self.folder,
            "poll_interval_s":    self.poll_interval_s,
            "enabled":            self.enabled,
            "sender_allowlist":   self.sender_allowlist or [],
            "auto_post_enabled":  self.auto_post_enabled,
            "configured":         bool(self.credentials_enc),
            "last_polled_at":     self.last_polled_at,
            "last_success_at":    self.last_success_at,
            "last_error":         self.last_error,
            "consecutive_failures": self.consecutive_failures,
            "messages_seen":      self.messages_seen,
            "documents_ingested": self.documents_ingested,
            "created_at":         self.created_at,
        }
        if include_secrets:
            data["credentials_enc"] = self.credentials_enc
        return data


class SeenMessageRow(Base):
    """Message ids already processed, so a re-read never re-ingests.

    Mail arrives at-least-once: a poller that dies mid-cycle re-reads on
    restart, and people forward and resend. The message id is the cheapest
    guard; the file fingerprint in ingestion_service catches the rest.
    """
    __tablename__ = "mailbox_seen_messages"

    id:          Mapped[str] = mapped_column(String, primary_key=True)
    mailbox_id:  Mapped[str] = mapped_column(String, nullable=False, index=True)
    message_id:  Mapped[str] = mapped_column(String, nullable=False, index=True)
    subject:     Mapped[str] = mapped_column(Text, nullable=False, default="")
    sender:      Mapped[str] = mapped_column(String, nullable=False, default="")
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    outcome:     Mapped[str]  = mapped_column(String, nullable=False, default="")
    document_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )
