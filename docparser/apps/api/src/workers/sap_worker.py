"""Celery tasks for SAP validation and MIRO posting.

validate_document     — fetch PO from SAP, compare against extracted data
post_miro_document    — build MIRO payload, post to SAP, record result

Follows the same asyncio.run() pattern as ocr_worker.py: Celery tasks are
synchronous functions that spin up a fresh event loop per invocation.
"""
import asyncio
from datetime import UTC, datetime
from typing import Any

import structlog
from celery import Task

from src.workers.celery_app import celery_app

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Bootstrap / teardown (shared with ocr_worker pattern)
# ---------------------------------------------------------------------------


async def _bootstrap() -> tuple[Any, Any]:
    from src.database import connect_db, get_database
    from src.utils.redis_client import connect_redis, get_redis

    await connect_db()
    await connect_redis()
    return get_database(), get_redis()


async def _teardown() -> None:
    from src.database import close_db
    from src.utils.redis_client import close_redis

    await close_db()
    await close_redis()


# ---------------------------------------------------------------------------
# validate_document
# ---------------------------------------------------------------------------


async def _run_validation(task: Task, document_id: str) -> None:
    from src.models.document import DocumentStatus
    from src.repositories.document_repository import DocumentRepository
    from src.services.sap_service import get_sap_service
    from src.services.validation_service import validate_invoice_against_po
    from src.utils.audit import SAP_VALIDATED, log_action

    bound_log = log.bind(document_id=document_id, task_id=task.request.id)
    db, redis = await _bootstrap()
    doc_repo = DocumentRepository(db)

    try:
        # ── 1. Fetch document ───────────────────────────────────────────
        doc = await doc_repo.find_by_document_id(document_id)
        if not doc:
            bound_log.error("document not found — validation aborted")
            return

        mongo_id = str(doc["_id"])
        extracted: dict[str, Any] = doc.get("extracted") or {}
        po_number: str = extracted.get("po_number") or ""

        if not po_number:
            bound_log.warning("no PO number in extracted data — validation skipped")
            await doc_repo.update_status(
                mongo_id,
                DocumentStatus.FAILED,
                error_entry={
                    "stage": "validation",
                    "message": "No PO number found in extracted data",
                    "detail": "MISSING_PO_NUMBER",
                    "timestamp": datetime.now(UTC),
                },
            )
            return

        # ── 2. Mark as validating ───────────────────────────────────────
        await doc_repo.update_status(mongo_id, DocumentStatus.VALIDATING)
        bound_log.info("validation started", po_number=po_number)

        # ── 3. Fetch PO details from SAP ────────────────────────────────
        sap_service = get_sap_service()
        sap_po = await sap_service.fetch_po_details(po_number)
        bound_log.info("SAP PO fetched", po_number=po_number)

        # ── 4. Validate invoice against PO ──────────────────────────────
        validation_result = await validate_invoice_against_po(extracted, sap_po)

        # ── 5. Persist validation result ────────────────────────────────
        await doc_repo.update_sap_validation(mongo_id, validation_result)
        bound_log.info(
            "validation persisted",
            overall=validation_result.get("overall_confidence"),
            is_valid=validation_result.get("is_valid"),
        )

        # ── 6. Publish event to Redis Stream ────────────────────────────
        await redis.xadd(
            "document:validated",
            {
                "document_id": document_id,
                "status": DocumentStatus.VALIDATED.value,
                "is_valid": str(validation_result.get("is_valid", False)),
                "overall_confidence": str(validation_result.get("overall_confidence", 0)),
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

        # ── 7. Audit log (fire-and-forget) ───────────────────────────────
        await log_action(
            document_id,
            SAP_VALIDATED,
            doc.get("uploaded_by", "system"),
            {
                "overall_confidence": validation_result.get("overall_confidence"),
                "is_valid": validation_result.get("is_valid"),
                "mismatch_count": len(validation_result.get("mismatches", [])),
            },
        )

    except Exception as exc:
        bound_log.error("validation failed", error=str(exc), attempt=task.request.retries)
        error_entry: dict[str, Any] = {
            "stage": "validation",
            "message": str(exc),
            "detail": type(exc).__name__,
            "timestamp": datetime.now(UTC),
        }
        doc = await doc_repo.find_by_document_id(document_id)
        if doc:
            mongo_id = str(doc["_id"])
            if task.request.retries >= task.max_retries:
                await doc_repo.update_status(
                    mongo_id, DocumentStatus.FAILED, error_entry=error_entry
                )
            else:
                await doc_repo.update_status(
                    mongo_id, DocumentStatus.EXTRACTED, error_entry=error_entry
                )
        raise

    finally:
        await _teardown()


@celery_app.task(
    name="validate_document",
    bind=True,
    max_retries=3,
    default_retry_delay=10,
)
def validate_document(self: Task, document_id: str) -> None:
    """Celery entry-point for SAP PO validation."""
    try:
        asyncio.run(_run_validation(self, document_id))
    except Exception as exc:
        countdown = 10 * (2 ** self.request.retries)
        raise self.retry(exc=exc, countdown=countdown)


# ---------------------------------------------------------------------------
# post_miro_document
# ---------------------------------------------------------------------------


async def _run_miro_posting(task: Task, document_id: str, posted_by: str) -> None:
    from src.models.document import DocumentStatus, MIROStatus
    from src.repositories.document_repository import DocumentRepository
    from src.services.miro_service import build_miro_payload
    from src.services.sap_service import get_sap_service
    from src.utils.audit import MIRO_FAILED, MIRO_POSTED, log_action

    bound_log = log.bind(document_id=document_id, task_id=task.request.id)
    db, redis = await _bootstrap()
    doc_repo = DocumentRepository(db)

    try:
        # ── 1. Fetch document ───────────────────────────────────────────
        doc = await doc_repo.find_by_document_id(document_id)
        if not doc:
            bound_log.error("document not found — MIRO posting aborted")
            return

        mongo_id = str(doc["_id"])
        extracted: dict[str, Any] = doc.get("extracted") or {}
        sap_validation: dict[str, Any] = doc.get("sap_validation") or {}

        po_number: str = extracted.get("po_number") or ""

        # ── 2. Mark as posting ──────────────────────────────────────────
        await doc_repo.update_status(mongo_id, DocumentStatus.POSTING)
        bound_log.info("MIRO posting started")

        # ── 3. Fetch fresh PO details for payload build ─────────────────
        sap_service = get_sap_service()
        sap_po = await sap_service.fetch_po_details(po_number) if po_number else None

        # Build payload (sap_po may be None if no PO number)
        from src.schemas.sap import SAPPOResponse
        payload = build_miro_payload(
            extracted,
            sap_po or SAPPOResponse(),
            sap_validation,
        )

        # ── 4. Post to SAP MIRO ─────────────────────────────────────────
        miro_resp = await sap_service.post_miro(payload)
        bound_log.info(
            "MIRO response",
            miro_number=miro_resp.miro_number,
            success=miro_resp.success,
        )

        # ── 5. Persist MIRO posting result ──────────────────────────────
        posting_data: dict[str, Any] = {
            "posted_at": datetime.now(UTC),
            "payload_sent": payload.model_dump(),
            "miro_number": miro_resp.miro_number,
            "sap_response": miro_resp.sap_response,
            "status": MIROStatus.SUCCESS.value if miro_resp.success else MIROStatus.FAILED.value,
        }
        await doc_repo.update_miro_posting(mongo_id, posting_data)

        # ── 6. Publish event to Redis Stream ────────────────────────────
        stream_name = "document:posted" if miro_resp.success else "document:post_failed"
        await redis.xadd(
            stream_name,
            {
                "document_id": document_id,
                "miro_number": miro_resp.miro_number,
                "status": miro_resp.status,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

        # ── 7. Audit log (fire-and-forget) ───────────────────────────────
        action = MIRO_POSTED if miro_resp.success else MIRO_FAILED
        await log_action(
            document_id,
            action,
            posted_by,
            {"miro_number": miro_resp.miro_number, "status": miro_resp.status},
        )

    except Exception as exc:
        bound_log.error("MIRO posting failed", error=str(exc), attempt=task.request.retries)
        error_entry: dict[str, Any] = {
            "stage": "miro_posting",
            "message": str(exc),
            "detail": type(exc).__name__,
            "timestamp": datetime.now(UTC),
        }
        doc = await doc_repo.find_by_document_id(document_id)
        if doc:
            mongo_id = str(doc["_id"])
            if task.request.retries >= task.max_retries:
                await doc_repo.update_status(
                    mongo_id, DocumentStatus.FAILED, error_entry=error_entry
                )
            else:
                await doc_repo.update_status(
                    mongo_id, DocumentStatus.VALIDATED, error_entry=error_entry
                )
        raise

    finally:
        await _teardown()


@celery_app.task(
    name="post_miro_document",
    bind=True,
    max_retries=3,
    default_retry_delay=15,
)
def post_miro_document(self: Task, document_id: str, posted_by: str = "system") -> None:
    """Celery entry-point for MIRO posting."""
    try:
        asyncio.run(_run_miro_posting(self, document_id, posted_by))
    except Exception as exc:
        countdown = 15 * (2 ** self.request.retries)
        raise self.retry(exc=exc, countdown=countdown)


# ---------------------------------------------------------------------------
# Direct async validation — used when Celery is not running
# ---------------------------------------------------------------------------


async def run_validation_direct(document_id: str) -> None:
    """Run SAP validation directly — routes to Service PO or Material PO based on invoice_subtype."""
    from src.database import get_database
    from src.models.document import DocumentStatus, InvoiceSubtype
    from src.repositories.document_repository import DocumentRepository
    from src.services.sap_service import get_sap_service
    from src.services.validation_service import validate_invoice_against_po, validate_service_invoice_against_po

    bound_log = log.bind(document_id=document_id)
    db = get_database()
    doc_repo = DocumentRepository(db)

    try:
        doc = await doc_repo.find_by_document_id(document_id)
        if not doc:
            bound_log.error("document not found — validation aborted")
            return

        mongo_id = str(doc["_id"])
        extracted: dict[str, Any] = doc.get("extracted") or {}
        invoice_subtype: str = doc.get("invoice_subtype") or ""
        is_freight_po = invoice_subtype == InvoiceSubtype.FREIGHT_PO
        is_service_po = invoice_subtype == InvoiceSubtype.SERVICE_PO
        po_number: str = extracted.get("po_number") or ""

        if not po_number:
            bound_log.warning("no PO number in extracted data — validation skipped")
            await doc_repo.update_status(
                mongo_id,
                DocumentStatus.FAILED,
                error_entry={
                    "stage": "validation",
                    "message": "No PO number found in extracted data",
                    "detail": "MISSING_PO_NUMBER",
                    "timestamp": datetime.now(UTC),
                },
            )
            return

        await doc_repo.update_status(mongo_id, DocumentStatus.VALIDATING)
        sap_service = get_sap_service()

        if is_service_po:
            # Service PO: validate via zspodetail/Detail, check SES approved
            bound_log.info("service PO validation started", po_number=po_number)
            sap_spo = await sap_service.fetch_service_po_details(po_number)
            bound_log.info("SAP Service PO fetched", po_number=po_number, ses_approved=sap_spo.ses_approved)
            if not sap_spo.ses_approved:
                await doc_repo.update_status(
                    mongo_id, DocumentStatus.FAILED,
                    error_entry={
                        "stage": "validation",
                        "message": "Service Entry Sheet (SES) not yet approved in SAP. Please approve the SES before posting.",
                        "detail": "SES_NOT_APPROVED",
                        "timestamp": datetime.now(UTC),
                    },
                )
                return
            validation_result = await validate_service_invoice_against_po(extracted, sap_spo)
        else:
            # Material PO and Freight PO both validate via zpo_grn/Detail
            po_label = "freight" if is_freight_po else "material"
            bound_log.info(f"{po_label} PO validation started", po_number=po_number)
            sap_po = await sap_service.fetch_po_details(po_number)
            bound_log.info("SAP PO fetched", po_number=po_number)
            validation_result = await validate_invoice_against_po(extracted, sap_po)

        await doc_repo.update_sap_validation(mongo_id, validation_result)
        bound_log.info(
            "direct validation complete",
            overall=validation_result.get("overall_confidence"),
            is_valid=validation_result.get("is_valid"),
        )

    except Exception as exc:
        bound_log.error("direct validation failed", error=str(exc))
        error_entry: dict[str, Any] = {
            "stage": "validation",
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


# ---------------------------------------------------------------------------
# Direct async MIRO posting — used when Celery is not running
# ---------------------------------------------------------------------------


async def run_miro_direct(document_id: str, posted_by: str = "system") -> None:
    """Run MIRO posting directly — routes to Service PO or Material PO MIRO based on invoice_subtype."""
    import traceback as _tb
    from src.database import get_database
    from src.models.document import DocumentStatus, InvoiceSubtype, MIROStatus
    from src.repositories.document_repository import DocumentRepository
    from src.services.miro_service import build_miro_payload, build_service_miro_payload, build_freight_miro_payload
    from src.services.sap_service import get_sap_service
    from src.schemas.sap import SAPPOResponse, SAPServicePOResponse

    bound_log = log.bind(document_id=document_id)
    bound_log.info("run_miro_direct entered")

    try:
        db = get_database()
        doc_repo = DocumentRepository(db)

        doc = await doc_repo.find_by_document_id(document_id)
        if not doc:
            bound_log.error("document not found — MIRO posting aborted")
            return

        mongo_id = str(doc["_id"])
        extracted: dict[str, Any] = doc.get("extracted") or {}
        sap_validation: dict[str, Any] = doc.get("sap_validation") or {}
        po_number: str = extracted.get("po_number") or ""
        invoice_subtype: str = doc.get("invoice_subtype") or ""
        is_freight_po = invoice_subtype == InvoiceSubtype.FREIGHT_PO
        is_service_po = invoice_subtype == InvoiceSubtype.SERVICE_PO
        bound_log.info("document loaded", mongo_id=mongo_id, po_number=po_number, invoice_subtype=invoice_subtype)

        await doc_repo.update_status(mongo_id, DocumentStatus.POSTING)

        sap_service = get_sap_service()

        if is_service_po:
            # Service PO: fetch via zspodetail/Detail, post to zmiro_post/MIRO
            bound_log.info("building Service PO MIRO payload", po_number=po_number)
            sap_spo = await sap_service.fetch_service_po_details(po_number) if po_number else SAPServicePOResponse()
            payload = build_service_miro_payload(extracted, sap_spo, sap_validation)
            bound_log.info("Service MIRO payload built", lines=len(payload.data[0].item_data))
            miro_resp = await sap_service.post_service_miro(payload)
        elif is_freight_po:
            # Freight PO: fetch via zpo_grn/Detail, post to zmiro_post/MIRO
            bound_log.info("building Freight MIRO payload", po_number=po_number)
            sap_po = await sap_service.fetch_po_details(po_number) if po_number else SAPPOResponse()
            bound_log.info("SAP PO fetched for freight", line_count=len(sap_po.PO_LINE_ITEMS))
            payload = build_freight_miro_payload(extracted, sap_po, sap_validation)
            bound_log.info("Freight MIRO payload built", lines=len(payload.data[0].item_data))
            miro_resp = await sap_service.post_service_miro(payload)
        else:
            # Material PO: fetch via zpo_grn/Detail, post to ZMIRO/MIRO
            bound_log.info("building Material PO MIRO payload", po_number=po_number)
            sap_po = await sap_service.fetch_po_details(po_number) if po_number else SAPPOResponse()
            bound_log.info("SAP PO fetched", line_count=len(sap_po.PO_LINE_ITEMS))
            payload = build_miro_payload(extracted, sap_po, sap_validation)
            bound_log.info("MIRO payload built", lines=len(payload.data[0].item_data))
            miro_resp = await sap_service.post_miro(payload)

        bound_log.info("MIRO response received", miro_number=miro_resp.miro_number, success=miro_resp.success)

        posting_data: dict[str, Any] = {
            "posted_at": datetime.now(UTC),
            "payload_sent": payload.model_dump(),
            "miro_number": miro_resp.miro_number,
            "sap_response": miro_resp.sap_response,
            "status": MIROStatus.SUCCESS.value if miro_resp.success else MIROStatus.FAILED.value,
        }
        await doc_repo.update_miro_posting(mongo_id, posting_data)
        bound_log.info("MIRO posting complete", miro_number=miro_resp.miro_number)

    except Exception as exc:
        bound_log.error(
            "direct MIRO posting failed",
            error=str(exc),
            exc_type=type(exc).__name__,
            traceback=_tb.format_exc(),
        )
        error_entry: dict[str, Any] = {
            "stage": "miro_posting",
            "message": str(exc) or type(exc).__name__,
            "detail": type(exc).__name__,
            "timestamp": datetime.now(UTC),
        }
        try:
            db2 = get_database()
            doc_repo2 = DocumentRepository(db2)
            doc2 = await doc_repo2.find_by_document_id(document_id)
            if doc2:
                await doc_repo2.update_status(
                    str(doc2["_id"]),
                    DocumentStatus.VALIDATED,  # keep VALIDATED so user can retry MIRO
                    error_entry=error_entry,
                )
        except Exception:
            pass
