"""Document ingestion — the one way a document enters the system.

Uploading used to be welded to the HTTP request: it took a CurrentUser and an
UploadFile, and read the tenant off the logged-in user. Email has neither, so
without this the mail poller would have grown a second copy of the same logic,
and the two would have drifted — the way the Celery and direct workers already
have, which is how a missing check survived in one path and not the other.

So the rules live here once: validate, hash, deduplicate, store, record, start
the pipeline. Both the web upload and the mailbox poller are thin callers.

Tenancy is the part that matters most. On the web the tenant comes from the
signed-in user; over email it comes from the mailbox that received the message —
never from the message itself, whose headers an attacker controls.
"""
from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import structlog

from src.models.document import TCODE_MAP, DocumentStatus, DocumentType, InvoiceSubtype, TCode

log = structlog.get_logger(__name__)


class DuplicateDocument(Exception):
    """The same bytes have already been ingested for this tenant."""

    def __init__(self, document_id: str) -> None:
        super().__init__(f"Already ingested as {document_id}")
        self.document_id = document_id


@dataclass(slots=True)
class IngestResult:
    document_id: str
    row_id: str
    duplicate_of: str | None = None
    started_pipeline: bool = False


@dataclass(slots=True)
class IngestSource:
    """Where a document came from, for audit and reporting.

    `channel` is 'web' or 'email'; `reference` is the message id for email so a
    document can be traced back to the mail that carried it.
    """
    channel: str = "web"
    actor: str = "system"
    reference: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


def _generate_document_id() -> str:
    return f"DOC-{datetime.now(UTC).year}-{random.randint(100_000, 999_999)}"


def file_fingerprint(file_bytes: bytes) -> str:
    """SHA-256 of the file, used to spot the same document arriving twice.

    Email is at-least-once: senders forward, CC, and resend "in case you missed
    it", and a reconnecting poller can re-read the same message. Hashing the
    bytes catches the identical-file case cheaply, before any OCR is paid for.
    """
    return hashlib.sha256(file_bytes).hexdigest()


async def find_by_fingerprint(fingerprint: str, tenant_id: str | None) -> str | None:
    """Return the document_id of an earlier ingest of these exact bytes.

    Scoped to the tenant: two customers may legitimately receive byte-identical
    documents, and one must never be told about the other's.
    """
    from sqlalchemy import text

    from src.database import AsyncSessionLocal

    sql = """
        SELECT document_id FROM documents
         WHERE file->>'fingerprint' = :fp
           AND (:tid::text IS NULL OR tenant_id = :tid)
         ORDER BY uploaded_at DESC LIMIT 1
    """
    async with AsyncSessionLocal() as session:
        row = (await session.execute(text(sql), {"fp": fingerprint, "tid": tenant_id})).first()
    return row[0] if row else None


def resolve_tcode(doc_type: DocumentType, subtype: InvoiceSubtype | None) -> TCode:
    """Non-PO invoices post through FB60; everything else follows its type."""
    return TCode.FB60 if subtype == InvoiceSubtype.NON_PO else TCODE_MAP[doc_type]


async def ingest_document(
    *,
    file_bytes: bytes,
    filename: str,
    content_type: str = "application/pdf",
    document_type: DocumentType = DocumentType.VENDOR_INVOICE,
    invoice_subtype: InvoiceSubtype | None = None,
    tenant_id: str | None = None,
    source: IngestSource | None = None,
    start_pipeline: bool = True,
    reject_duplicates: bool = False,
) -> IngestResult:
    """Take raw bytes and make them a document in flight.

    Raises ValidationError if the file is not acceptable, and DuplicateDocument
    when `reject_duplicates` is set and these bytes were seen before. The web
    upload keeps its historical behaviour of allowing a re-upload; the mail
    poller sets the flag, because a mailbox will re-present the same attachment
    for reasons that have nothing to do with intent.
    """
    from src.database import AsyncSessionLocal
    from src.repositories.document_repository import DocumentRepository
    from src.services.storage_service import build_s3_key, upload_file, validate_upload

    src = source or IngestSource()
    validate_upload(file_bytes, filename, content_type)

    fingerprint = file_fingerprint(file_bytes)
    seen_as = await find_by_fingerprint(fingerprint, tenant_id)
    if seen_as:
        log.info("identical file already ingested",
                 document_id=seen_as, channel=src.channel, filename=filename)
        if reject_duplicates:
            raise DuplicateDocument(seen_as)

    document_id = _generate_document_id()
    s3_key = build_s3_key(document_type.value, document_id, filename)
    tcode = resolve_tcode(document_type, invoice_subtype)

    doc_data: dict[str, Any] = {
        "document_id":     document_id,
        "type":            document_type.value,
        "tcode":           tcode.value,
        "invoice_subtype": invoice_subtype.value if invoice_subtype else None,
        "status":          DocumentStatus.UPLOADED.value,
        "uploaded_by":     src.actor,
        "uploaded_at":     datetime.now(UTC),
        "tenant_id":       tenant_id,
        "source":          src.channel,
        "source_reference": src.reference,
        "source_metadata": src.metadata,
        "file": {
            "original_name": filename,
            "s3_key":        s3_key,
            "size_bytes":    len(file_bytes),
            "mime_type":     content_type,
            "fingerprint":   fingerprint,
        },
        "error_log": [],
    }

    async with AsyncSessionLocal() as session:
        repo = DocumentRepository(session)
        row_id = await repo.create(doc_data)
        await session.commit()

    log.info("document record created",
             document_id=document_id, channel=src.channel, tenant_id=tenant_id)

    # Store the bytes. A failure here leaves a FAILED row rather than a silent
    # gap, so the document is visible and can be retried.
    try:
        actual_key = await upload_file(
            file_bytes, filename, content_type, document_type.value, document_id,
            uploaded_by=src.actor,
        )
    except Exception as exc:
        async with AsyncSessionLocal() as session:
            await DocumentRepository(session).update_status(
                row_id, DocumentStatus.FAILED,
                error_entry={"stage": "upload", "message": f"Storage failed: {exc}",
                             "detail": type(exc).__name__,
                             "timestamp": datetime.now(UTC).isoformat()},
            )
            await session.commit()
        raise

    if actual_key != s3_key:
        async with AsyncSessionLocal() as session:
            repo = DocumentRepository(session)
            doc = await repo.find_by_id(row_id)
            if doc:
                file_data = dict(doc.get("file") or {})
                file_data["s3_key"] = actual_key
                await repo.update(row_id, {"file": file_data})
                await session.commit()

    started = False
    if start_pipeline:
        import asyncio

        from src.workers.pipeline_worker import run_pipeline

        async def _run() -> None:
            try:
                await run_pipeline(document_id)
            except Exception as exc:
                log.error("ingest pipeline crashed",
                          document_id=document_id, error=str(exc), exc_info=True)

        asyncio.create_task(_run(), name=f"pipeline-{document_id}")
        started = True

    return IngestResult(
        document_id=document_id,
        row_id=row_id,
        duplicate_of=seen_as,
        started_pipeline=started,
    )
