"""Celery tasks for asynchronous document OCR extraction.

Celery runs tasks synchronously (def, not async def); we bridge to async code
via asyncio.run(), which creates a fresh event loop per task invocation.
This is the standard pattern for Celery + asyncio without a custom pool.

Tasks
-----
  extract_document          — download file, call OCR, update MongoDB
  cleanup_failed_documents  — purge docs stuck in 'failed' for > 7 days
"""
import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from celery import Task

from src.workers.celery_app import celery_app

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Helpers — run once per task in the fresh event loop
# ---------------------------------------------------------------------------


async def _bootstrap() -> tuple[Any, Any, Any]:
    """Connect to DB and Redis inside the task's event loop; return handles."""
    from src.database import connect_db, get_database
    from src.utils.redis_client import connect_redis, get_redis

    await connect_db()
    await connect_redis()
    return get_database(), get_redis(), None


async def _teardown() -> None:
    from src.database import close_db
    from src.utils.redis_client import close_redis

    await close_db()
    await close_redis()


# ---------------------------------------------------------------------------
# extract_document task
# ---------------------------------------------------------------------------


async def _run_extraction(task: Task, document_id: str) -> None:
    """Async implementation — called inside asyncio.run() by the Celery task."""
    from src.models.document import DocumentStatus
    from src.repositories.document_repository import DocumentRepository
    from src.services.ocr_service import extract_vendor_invoice
    from src.services.storage_service import download_file

    bound_log = log.bind(document_id=document_id, task_id=task.request.id)

    db, redis, _ = await _bootstrap()
    doc_repo = DocumentRepository(db)

    try:
        # ── 1. Fetch document ───────────────────────────────────────────
        doc = await doc_repo.find_by_document_id(document_id)
        if not doc:
            bound_log.error("document not found — task aborted")
            return

        mongo_id = str(doc["_id"])
        s3_key: str = doc.get("file", {}).get("s3_key", "")
        mime_type: str = doc.get("file", {}).get("mime_type", "application/pdf")

        # ── 2. Mark as extracting ───────────────────────────────────────
        await doc_repo.update_status(mongo_id, DocumentStatus.EXTRACTING)
        bound_log.info("extraction started", s3_key=s3_key)

        # ── 3. Download file bytes from S3 ──────────────────────────────
        file_bytes = await download_file(s3_key)
        bound_log.info("file downloaded from S3", size=len(file_bytes))

        # ── 4. Run OCR ──────────────────────────────────────────────────
        extracted_data = await extract_vendor_invoice(file_bytes, mime_type)

        # ── 5. Persist extracted data ───────────────────────────────────
        await doc_repo.update_extracted_data(mongo_id, extracted_data)
        bound_log.info(
            "extraction complete",
            invoice_no=extracted_data.get("invoice_no"),
            confidence=extracted_data.get("confidence_score"),
        )

        # ── 6. Publish event to Redis Stream ────────────────────────────
        await redis.xadd(
            "document:extracted",
            {
                "document_id": document_id,
                "status": DocumentStatus.EXTRACTED.value,
                "confidence": str(extracted_data.get("confidence_score", 0)),
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

    except Exception as exc:
        bound_log.error("extraction failed", error=str(exc), attempt=task.request.retries)

        error_entry: dict[str, Any] = {
            "stage": "extraction",
            "message": str(exc),
            "detail": type(exc).__name__,
            "timestamp": datetime.now(UTC),
        }

        doc = await doc_repo.find_by_document_id(document_id)
        if doc:
            mongo_id = str(doc["_id"])
            new_retry = await doc_repo.increment_retry(mongo_id)

            if task.request.retries >= task.max_retries:
                await doc_repo.update_status(
                    mongo_id,
                    DocumentStatus.FAILED,
                    error_entry=error_entry,
                )
            else:
                await doc_repo.update_status(
                    mongo_id,
                    DocumentStatus.UPLOADED,  # reset so next retry can pick it up
                    error_entry=error_entry,
                )
        raise  # let Celery handle retry / failure recording

    finally:
        await _teardown()


@celery_app.task(
    name="extract_document",
    bind=True,
    max_retries=3,
    default_retry_delay=5,
)
def extract_document(self: Task, document_id: str) -> None:
    """Celery entry-point for document OCR extraction."""
    try:
        asyncio.run(_run_extraction(self, document_id))
    except Exception as exc:
        # Exponential back-off: 5s, 10s, 20s
        countdown = 5 * (2 ** self.request.retries)
        raise self.retry(exc=exc, countdown=countdown)


# ---------------------------------------------------------------------------
# cleanup_failed_documents task (Beat schedule)
# ---------------------------------------------------------------------------


async def _run_cleanup() -> None:
    """Remove documents stuck in FAILED status for more than 7 days."""
    from src.repositories.document_repository import DocumentRepository

    db, _, _ = await _bootstrap()
    doc_repo = DocumentRepository(db)
    cutoff = datetime.now(UTC) - timedelta(days=7)

    docs = await doc_repo.list(
        filter={"status": "failed", "updated_at": {"$lt": cutoff}},
        limit=200,
    )

    deleted = 0
    for doc in docs:
        await doc_repo.delete(str(doc["_id"]))
        deleted += 1

    log.info("cleanup complete", deleted=deleted)
    await _teardown()


@celery_app.task(name="cleanup_failed_documents")
def cleanup_failed_documents() -> None:
    asyncio.run(_run_cleanup())


# ---------------------------------------------------------------------------
# Direct async extraction — used when Celery is not running
# ---------------------------------------------------------------------------


async def run_extraction_direct(document_id: str) -> None:
    """Run OCR extraction directly in the FastAPI event loop (no Celery needed).

    Called via asyncio.create_task() from the upload route so the HTTP response
    is returned immediately while extraction runs in the background.
    """
    from src.database import get_database
    from src.models.document import DocumentStatus
    from src.repositories.document_repository import DocumentRepository
    from src.services.ocr_service import extract_vendor_invoice
    from src.services.storage_service import download_file

    bound_log = log.bind(document_id=document_id)
    db = get_database()
    doc_repo = DocumentRepository(db)

    try:
        doc = await doc_repo.find_by_document_id(document_id)
        if not doc:
            bound_log.error("document not found — extraction aborted")
            return

        mongo_id = str(doc["_id"])
        s3_key: str = doc.get("file", {}).get("s3_key", "")
        mime_type: str = doc.get("file", {}).get("mime_type", "application/pdf")

        await doc_repo.update_status(mongo_id, DocumentStatus.EXTRACTING)
        bound_log.info("direct extraction started", s3_key=s3_key)

        file_bytes = await download_file(s3_key)
        bound_log.info("file downloaded", size=len(file_bytes))

        extracted_data = await extract_vendor_invoice(file_bytes, mime_type)

        await doc_repo.update_extracted_data(mongo_id, extracted_data)
        bound_log.info(
            "direct extraction complete",
            invoice_no=extracted_data.get("invoice_no"),
            confidence=extracted_data.get("confidence_score"),
        )


    except Exception as exc:
        bound_log.error("direct extraction failed", error=str(exc))
        error_entry: dict[str, Any] = {
            "stage": "extraction",
            "message": str(exc),
            "detail": type(exc).__name__,
            "timestamp": datetime.now(UTC),
        }
        try:
            doc2 = await doc_repo.find_by_document_id(document_id)
            if doc2:
                await doc_repo.update_status(
                    str(doc2["_id"]),
                    DocumentStatus.FAILED,
                    error_entry=error_entry,
                )
        except Exception:
            pass
