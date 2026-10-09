"""Mailbox polling — invoices arrive by email and process themselves.

One scheduler serves every tenant. The important property is that customers are
isolated from each other's problems: mailboxes are polled concurrently with a
bounded pool, each under its own timeout, and a mailbox that keeps failing backs
off instead of being retried every minute forever. One customer's expired Azure
secret must not delay another customer's invoices.

The tenant is taken from the mailbox row and never from the message. To, From
and Subject are all set by whoever sent the mail, so the only trustworthy
statement about ownership is which authenticated mailbox it was found in.
"""
from __future__ import annotations

import asyncio
import re
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog

from src.config import settings

log = structlog.get_logger(__name__)

# Sangam's quality-release notification arrives as a plain email on the same
# shared mailbox, not an API call — e.g. 'The PO "4500022737" with invoice is
# moved to unrestricted and ready for miro park'. No attachment, so it would
# never reach process_message's PDF loop; it is matched on subject+body here
# before that loop runs. Requires both the PO number AND "unrestricted" so an
# unrelated email that happens to mention a PO number is never mistaken for one.
_RELEASE_PO_PATTERN = re.compile(r'PO\s*"?(\d{6,12})"?', re.IGNORECASE)
_RELEASE_KEYWORDS = ("unrestricted", "park")

# After this many consecutive failures a mailbox is polled progressively less
# often — capped so a recovered mailbox is still picked up within the hour.
_BACKOFF_AFTER = 3
_MAX_BACKOFF_S = 3600


def _sender_allowed(sender: str, allowlist: list[str]) -> bool:
    """True if this sender is pre-trusted for unattended posting.

    An entry may be a whole address or a bare domain ('@vendor.com'). An empty
    allowlist trusts nobody: mail still arrives and is processed, but it will
    not post by itself. That default matters — a published invoices@ address is
    an obvious target for invoice fraud, and auto-posting mail from strangers is
    exactly the wrong thing to do by accident.
    """
    if not allowlist:
        return False
    sender = (sender or "").strip().lower()
    for entry in allowlist:
        rule = (entry or "").strip().lower()
        if not rule:
            continue
        if rule.startswith("@") and sender.endswith(rule):
            return True
        if sender == rule:
            return True
    return False


async def _already_seen(mailbox_id: str, message_id: str) -> bool:
    from sqlalchemy import select

    from src.database import AsyncSessionLocal
    from src.models.mailbox import SeenMessageRow

    async with AsyncSessionLocal() as session:
        found = (await session.execute(
            select(SeenMessageRow.id).where(
                SeenMessageRow.mailbox_id == mailbox_id,
                SeenMessageRow.message_id == message_id,
            )
        )).first()
    return found is not None


async def _record_seen(mailbox_id: str, message: Any, outcome: str,
                       document_ids: list[str]) -> None:
    from src.database import AsyncSessionLocal
    from src.models.mailbox import SeenMessageRow

    async with AsyncSessionLocal() as session:
        session.add(SeenMessageRow(
            id=str(uuid.uuid4()),
            mailbox_id=mailbox_id,
            message_id=message.message_id,
            subject=(message.subject or "")[:900],
            sender=message.sender or "",
            received_at=message.received_at,
            outcome=outcome,
            document_ids=document_ids,
        ))
        await session.commit()


async def _update_health(mailbox_id: str, **fields: Any) -> None:
    from sqlalchemy import update

    from src.database import AsyncSessionLocal
    from src.models.mailbox import MailboxRow

    async with AsyncSessionLocal() as session:
        await session.execute(update(MailboxRow).where(MailboxRow.id == mailbox_id).values(**fields))
        await session.commit()


def _route_tenant(mailbox: dict[str, Any], sender: str) -> str:
    """Which tenant a message belongs to — almost always just the mailbox's own.

    `tenant_routes` only matters when one inbox is shared by more than one
    company (see the field's docstring on MailboxRow): the first entry whose
    sender/domain matches wins, otherwise this falls back to the mailbox's own
    tenant exactly as it always has.
    """
    sender_clean = (sender or "").strip().lower()
    for route in (mailbox.get("tenant_routes") or []):
        rule = str(route.get("sender") or "").strip().lower()
        if not rule:
            continue
        if rule.startswith("@") and sender_clean.endswith(rule):
            return route["tenant_id"]
        if sender_clean == rule:
            return route["tenant_id"]
    return mailbox["tenant_id"]


def _extract_release_po(message: Any) -> str:
    """The PO number if this message is a quality-release notification, else ''."""
    text = f"{message.subject or ''} {getattr(message, 'body', '') or ''}"
    low = text.lower()
    if not all(kw in low for kw in _RELEASE_KEYWORDS):
        return ""
    match = _RELEASE_PO_PATTERN.search(text)
    return match.group(1) if match else ""


async def _handle_release_notification(mailbox: dict[str, Any], message: Any) -> bool:
    """If this message is a Sangam-style release notification, auto-park the
    matching document and report True so the caller skips normal PDF ingestion
    for it (there is nothing to ingest — the message has no attachment)."""
    po_number = _extract_release_po(message)
    if not po_number:
        return False

    bound = log.bind(mailbox=mailbox["address"], po_number=po_number)

    from sqlalchemy import select

    from src.database import AsyncSessionLocal
    from src.models.document import DocumentRow, DocumentStatus

    async with AsyncSessionLocal() as session:
        stmt = (
            select(DocumentRow)
            .where(
                DocumentRow.extracted["po_number"].astext == po_number,
                DocumentRow.status == DocumentStatus.GR_POSTED.value,
                DocumentRow.grn_posting["pending_quality_release"].astext == "true",
            )
            .order_by(DocumentRow.uploaded_at.desc())
            .limit(1)
        )
        doc = (await session.execute(stmt)).scalars().first()

    if not doc:
        bound.warning("release notification received but no matching document awaiting quality release")
        return True  # still handled — this email is not an invoice, do not try to ingest it as one

    bound.info("release notification matched — auto-parking MIRO", document_id=doc.document_id)
    try:
        from src.workers.sap_worker import run_miro_park_direct
        await run_miro_park_direct(doc.document_id, posted_by="sap-notification")
    except Exception as exc:
        bound.error("auto-park from release notification failed", document_id=doc.document_id, error=str(exc))
    return True


async def process_message(mailbox: dict[str, Any], message: Any) -> list[str]:
    """Ingest a message's PDF attachments. Returns the document ids created."""
    from src.models.document import DocumentType
    from src.services.ingestion_service import (
        DuplicateDocument, IngestSource, ingest_document,
    )

    tenant_id = _route_tenant(mailbox, message.sender)
    bound = log.bind(mailbox=mailbox["address"], sender=message.sender, tenant_id=tenant_id)
    trusted = _sender_allowed(message.sender, mailbox.get("sender_allowlist") or [])
    created: list[str] = []

    attachments = message.attachments[: settings.MAIL_MAX_ATTACHMENTS]
    for att in attachments:
        if len(att.content) < settings.MAIL_MIN_ATTACHMENT_BYTES:
            bound.info("attachment too small — skipped",
                       filename=att.filename, size=len(att.content))
            continue
        try:
            result = await ingest_document(
                file_bytes=att.content,
                filename=att.filename,
                content_type=att.content_type,
                document_type=DocumentType.VENDOR_INVOICE,
                tenant_id=tenant_id,
                source=IngestSource(
                    channel="email",
                    actor=message.sender or "email",
                    reference=message.message_id,
                    metadata={
                        "subject": message.subject,
                        "mailbox": mailbox["address"],
                        "sender_trusted": trusted,
                        # Recorded so the pipeline can refuse to auto-post mail
                        # from an unknown sender even when the tenant allows it.
                        "auto_post_allowed": bool(trusted and mailbox.get("auto_post_enabled")),
                    },
                ),
                reject_duplicates=True,
            )
            created.append(result.document_id)
            bound.info("ingested from mail",
                       document_id=result.document_id, filename=att.filename, trusted=trusted)
        except DuplicateDocument as dup:
            bound.info("attachment already ingested — skipped",
                       filename=att.filename, original=dup.document_id)
        except Exception as exc:
            bound.error("could not ingest attachment", filename=att.filename, error=str(exc))

    return created


async def poll_mailbox(mailbox: dict[str, Any]) -> dict[str, Any]:
    """Poll one mailbox. Never raises — the result describes what happened."""
    from src.services.mail_providers import (
        MailAuthError, MailTransientError, build_provider,
    )
    from src.services.secret_store import decrypt_dict

    bound = log.bind(mailbox=mailbox["address"], tenant_id=mailbox["tenant_id"])
    summary = {"messages": 0, "documents": 0, "error": ""}

    try:
        credentials = decrypt_dict(mailbox.get("credentials_enc") or "")
        provider = build_provider(
            mailbox["provider"], credentials, mailbox["address"], mailbox.get("folder", "")
        )
        messages = await provider.fetch_unread()
    except MailAuthError as exc:
        # Permanent until someone fixes the configuration; count it so the
        # mailbox backs off rather than retrying every minute.
        bound.error("mailbox authentication failed", error=str(exc))
        summary["error"] = str(exc)
        await _update_health(
            mailbox["id"], last_polled_at=datetime.now(UTC), last_error=str(exc)[:900],
            consecutive_failures=mailbox.get("consecutive_failures", 0) + 1,
        )
        return summary
    except (MailTransientError, Exception) as exc:
        bound.warning("mailbox unreachable", error=str(exc))
        summary["error"] = str(exc)
        await _update_health(
            mailbox["id"], last_polled_at=datetime.now(UTC), last_error=str(exc)[:900],
            consecutive_failures=mailbox.get("consecutive_failures", 0) + 1,
        )
        return summary

    for message in messages:
        if not message.message_id:
            continue
        if await _already_seen(mailbox["id"], message.message_id):
            # Mark it read so it stops coming back, but do not ingest again.
            try:
                await provider.mark_read(message)
            except Exception:
                pass
            continue

        summary["messages"] += 1

        if await _handle_release_notification(mailbox, message):
            await _record_seen(mailbox["id"], message, "quality_release_notification", [])
            try:
                await provider.mark_read(message)
            except Exception as exc:
                bound.warning("could not mark message read", error=str(exc))
            continue

        document_ids = await process_message(mailbox, message)
        summary["documents"] += len(document_ids)

        outcome = "ingested" if document_ids else "no_pdf_attachment"
        await _record_seen(mailbox["id"], message, outcome, document_ids)

        # Only marked read once its contents are safely recorded, so a crash
        # mid-message leaves the mail to be picked up again rather than lost.
        try:
            await provider.mark_read(message)
        except Exception as exc:
            bound.warning("could not mark message read", error=str(exc))

    await _update_health(
        mailbox["id"],
        last_polled_at=datetime.now(UTC),
        last_success_at=datetime.now(UTC),
        last_error="",
        consecutive_failures=0,
        messages_seen=mailbox.get("messages_seen", 0) + summary["messages"],
        documents_ingested=mailbox.get("documents_ingested", 0) + summary["documents"],
    )
    if summary["messages"]:
        bound.info("mailbox polled",
                   messages=summary["messages"], documents=summary["documents"])
    return summary


def _is_due(mailbox: dict[str, Any], now: datetime) -> bool:
    """Whether this mailbox should be polled on this tick.

    A failing mailbox is polled less and less often, so a broken configuration
    costs one attempt an hour rather than one a minute.
    """
    last = mailbox.get("last_polled_at")
    if not last:
        return True
    interval = mailbox.get("poll_interval_s") or 60
    failures = mailbox.get("consecutive_failures", 0)
    if failures >= _BACKOFF_AFTER:
        interval = min(interval * (2 ** (failures - _BACKOFF_AFTER + 1)), _MAX_BACKOFF_S)
    return (now - last).total_seconds() >= interval


async def _enabled_mailboxes() -> list[dict[str, Any]]:
    from sqlalchemy import select

    from src.database import AsyncSessionLocal
    from src.models.mailbox import MailboxRow

    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(MailboxRow).where(MailboxRow.enabled.is_(True))
        )).scalars().all()
    return [{**r.to_dict(include_secrets=True), "credentials_enc": r.credentials_enc} for r in rows]


async def poll_once() -> dict[str, Any]:
    """One scheduling pass over every due mailbox."""
    now = datetime.now(UTC)
    mailboxes = [m for m in await _enabled_mailboxes() if _is_due(m, now)]
    if not mailboxes:
        return {"polled": 0, "documents": 0}

    limit = asyncio.Semaphore(settings.MAIL_POLL_CONCURRENCY)

    async def _one(mailbox: dict[str, Any]) -> dict[str, Any]:
        async with limit:
            try:
                async with asyncio.timeout(settings.MAIL_POLL_TIMEOUT_SECONDS):
                    return await poll_mailbox(mailbox)
            except TimeoutError:
                log.warning("mailbox poll timed out", mailbox=mailbox["address"])
                await _update_health(
                    mailbox["id"], last_polled_at=datetime.now(UTC),
                    last_error="Poll timed out",
                    consecutive_failures=mailbox.get("consecutive_failures", 0) + 1,
                )
                return {"messages": 0, "documents": 0, "error": "timeout"}

    results = await asyncio.gather(*(_one(m) for m in mailboxes))
    return {
        "polled": len(mailboxes),
        "documents": sum(r.get("documents", 0) for r in results),
    }


async def start_mail_worker() -> None:
    """Entry point for asyncio.create_task(); runs until cancelled."""
    if not settings.MAIL_INGEST_ENABLED:
        log.info("mail ingestion disabled — worker not started")
        return

    log.info("mail ingestion worker started",
             concurrency=settings.MAIL_POLL_CONCURRENCY)
    try:
        while True:
            try:
                await poll_once()
            except Exception as exc:
                # The scheduler itself must survive anything a mailbox throws.
                log.error("mail poll cycle failed", error=str(exc))
            await asyncio.sleep(15)
    except asyncio.CancelledError:
        log.info("mail ingestion worker stopped")
