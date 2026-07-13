"""Celery tasks for asynchronous document OCR extraction."""
import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from celery import Task

from src.workers.celery_app import celery_app

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# extract_document task
# ---------------------------------------------------------------------------


async def _run_extraction(task: Task, document_id: str) -> None:
    from src.database import AsyncSessionLocal
    from src.models.document import DocumentStatus
    from src.repositories.document_repository import DocumentRepository
    from src.services.ocr_service import extract_vendor_invoice
    from src.services.storage_service import download_file
    from src.utils.redis_client import connect_redis, get_redis

    await connect_redis()
    redis = get_redis()
    bound_log = log.bind(document_id=document_id, task_id=task.request.id)

    async with AsyncSessionLocal() as session:
        doc_repo = DocumentRepository(session)
        try:
            doc = await doc_repo.find_by_document_id(document_id)
            if not doc:
                bound_log.error("document not found — task aborted")
                return

            doc_id = doc["id"]
            s3_key: str = (doc.get("file") or {}).get("s3_key", "")
            mime_type: str = (doc.get("file") or {}).get("mime_type", "application/pdf")

            await doc_repo.update_status(doc_id, DocumentStatus.EXTRACTING)
            bound_log.info("extraction started", s3_key=s3_key)

            file_bytes = await download_file(s3_key)
            bound_log.info("file downloaded from S3", size=len(file_bytes))

            extracted_data = await extract_vendor_invoice(file_bytes, mime_type)
            await doc_repo.update_extracted_data(doc_id, extracted_data)
            await session.commit()

            bound_log.info("extraction complete",
                           invoice_no=extracted_data.get("invoice_no"),
                           confidence=extracted_data.get("confidence_score"))

            await redis.xadd("document:extracted", {
                "document_id": document_id,
                "status":      DocumentStatus.EXTRACTED.value,
                "confidence":  str(extracted_data.get("confidence_score", 0)),
                "timestamp":   datetime.now(UTC).isoformat(),
            })

        except Exception as exc:
            bound_log.error("extraction failed", error=str(exc), attempt=task.request.retries)
            error_entry: dict[str, Any] = {
                "stage": "extraction", "message": str(exc),
                "detail": type(exc).__name__, "timestamp": datetime.now(UTC).isoformat(),
            }
            doc2 = await doc_repo.find_by_document_id(document_id)
            if doc2:
                new_status = DocumentStatus.FAILED if task.request.retries >= task.max_retries else DocumentStatus.UPLOADED
                await doc_repo.update_status(doc2["id"], new_status, error_entry=error_entry)
                await session.commit()
            raise


@celery_app.task(name="extract_document", bind=True, max_retries=3, default_retry_delay=5)
def extract_document(self: Task, document_id: str) -> None:
    try:
        asyncio.run(_run_extraction(self, document_id))
    except Exception as exc:
        raise self.retry(exc=exc, countdown=5 * (2 ** self.request.retries))


# ---------------------------------------------------------------------------
# cleanup_failed_documents task (Beat schedule)
# ---------------------------------------------------------------------------


async def _run_cleanup() -> None:
    from src.database import AsyncSessionLocal
    from src.repositories.document_repository import DocumentRepository

    cutoff = datetime.now(UTC) - timedelta(days=7)
    async with AsyncSessionLocal() as session:
        doc_repo = DocumentRepository(session)
        docs, _ = await doc_repo.list_documents(filter_query={"status": "failed"}, limit=200)
        deleted = 0
        for doc in docs:
            updated_at = doc.get("updated_at")
            if updated_at and updated_at < cutoff:
                await doc_repo.delete(doc["id"])
                deleted += 1
        await session.commit()

    log.info("cleanup complete", deleted=deleted)


@celery_app.task(name="cleanup_failed_documents")
def cleanup_failed_documents() -> None:
    asyncio.run(_run_cleanup())


# ---------------------------------------------------------------------------
# Direct async extraction — used when Celery is not running
# ---------------------------------------------------------------------------


async def run_extraction_direct(document_id: str) -> None:
    """Run OCR extraction directly in the FastAPI event loop (no Celery needed)."""
    from src.database import AsyncSessionLocal
    from src.models.document import DocumentStatus
    from src.repositories.document_repository import DocumentRepository
    from src.services.ocr_service import extract_vendor_invoice
    from src.services.storage_service import download_file

    bound_log = log.bind(document_id=document_id)

    async with AsyncSessionLocal() as session:
        doc_repo = DocumentRepository(session)
        try:
            doc = await doc_repo.find_by_document_id(document_id)
            if not doc:
                bound_log.error("document not found — extraction aborted")
                return

            doc_id = doc["id"]
            s3_key: str = (doc.get("file") or {}).get("s3_key", "")
            mime_type: str = (doc.get("file") or {}).get("mime_type", "application/pdf")

            await doc_repo.update_status(doc_id, DocumentStatus.EXTRACTING)
            await session.commit()
            bound_log.info("direct extraction started", s3_key=s3_key)

            file_bytes = await download_file(s3_key)
            extracted_data = await extract_vendor_invoice(file_bytes, mime_type)
            await doc_repo.update_extracted_data(doc_id, extracted_data)
            await session.commit()

            bound_log.info("direct extraction complete",
                           invoice_no=extracted_data.get("invoice_no"),
                           confidence=extracted_data.get("confidence_score"))

        except Exception as exc:
            bound_log.error("direct extraction failed", error=str(exc))
            error_entry: dict[str, Any] = {
                "stage": "extraction", "message": str(exc),
                "detail": type(exc).__name__, "timestamp": datetime.now(UTC).isoformat(),
            }
            try:
                doc2 = await doc_repo.find_by_document_id(document_id)
                if doc2:
                    await doc_repo.update_status(doc2["id"], DocumentStatus.FAILED, error_entry=error_entry)
                    await session.commit()
            except Exception:
                pass
