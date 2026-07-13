"""Celery tasks for SAP validation and MIRO posting."""
import asyncio
from datetime import UTC, datetime
from typing import Any

import structlog
from celery import Task

from src.workers.celery_app import celery_app

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# validate_document
# ---------------------------------------------------------------------------


async def _run_validation(task: Task, document_id: str) -> None:
    from src.database import AsyncSessionLocal
    from src.models.document import DocumentStatus
    from src.repositories.document_repository import DocumentRepository
    from src.services.sap_service import get_sap_service
    from src.services.validation_service import validate_invoice_against_po
    from src.utils.audit import SAP_VALIDATED, log_action
    from src.utils.redis_client import connect_redis, get_redis

    await connect_redis()
    redis = get_redis()
    bound_log = log.bind(document_id=document_id, task_id=task.request.id)

    async with AsyncSessionLocal() as session:
        doc_repo = DocumentRepository(session)
        try:
            doc = await doc_repo.find_by_document_id(document_id)
            if not doc:
                bound_log.error("document not found — validation aborted")
                return

            doc_id = doc["id"]
            extracted: dict[str, Any] = doc.get("extracted") or {}
            po_number: str = extracted.get("po_number") or ""

            if not po_number:
                await doc_repo.update_status(doc_id, DocumentStatus.FAILED, error_entry={
                    "stage": "validation", "message": "No PO number found in extracted data",
                    "detail": "MISSING_PO_NUMBER", "timestamp": datetime.now(UTC).isoformat(),
                })
                await session.commit()
                return

            await doc_repo.update_status(doc_id, DocumentStatus.VALIDATING)
            await session.commit()

            sap_service = get_sap_service()
            try:
                sap_po = await sap_service.fetch_po_details(po_number)
            except Exception as sap_exc:
                bound_log.error("SAP PO fetch failed — stopping validation", error=str(sap_exc))
                error_entry: dict[str, Any] = {
                    "stage": "sap_fetch", "message": str(sap_exc),
                    "detail": type(sap_exc).__name__, "timestamp": datetime.now(UTC).isoformat(),
                }
                await doc_repo.update_status(doc_id, DocumentStatus.FAILED, error_entry=error_entry)
                await session.commit()
                return

            validation_result = await validate_invoice_against_po(extracted, sap_po)
            is_valid: bool = bool(validation_result.get("is_valid", False))
            await doc_repo.update_sap_validation(doc_id, validation_result, is_valid=is_valid)
            await session.commit()

            stream_status = DocumentStatus.VALIDATED.value if is_valid else DocumentStatus.FAILED.value
            await redis.xadd("document:validated", {
                "document_id":        document_id,
                "status":             stream_status,
                "is_valid":           str(is_valid),
                "overall_confidence": str(validation_result.get("overall_confidence", 0)),
                "timestamp":          datetime.now(UTC).isoformat(),
            })

            await log_action(document_id, SAP_VALIDATED, doc.get("uploaded_by", "system"), {
                "overall_confidence": validation_result.get("overall_confidence"),
                "is_valid":           validation_result.get("is_valid"),
                "mismatch_count":     len(validation_result.get("mismatches", [])),
            })

        except Exception as exc:
            bound_log.error("validation failed unexpectedly", error=str(exc), attempt=task.request.retries)
            err: dict[str, Any] = {
                "stage": "validation", "message": str(exc),
                "detail": type(exc).__name__, "timestamp": datetime.now(UTC).isoformat(),
            }
            try:
                doc2 = await doc_repo.find_by_document_id(document_id)
                if doc2:
                    await doc_repo.update_status(doc2["id"], DocumentStatus.FAILED, error_entry=err)
                    await session.commit()
            except Exception:
                pass
            raise


@celery_app.task(name="validate_document", bind=True, max_retries=1, default_retry_delay=10)
def validate_document(self: Task, document_id: str) -> None:
    try:
        asyncio.run(_run_validation(self, document_id))
    except Exception as exc:
        if self.request.retries >= self.max_retries:
            log.error("validation task exhausted retries", document_id=document_id, error=str(exc))
            return
        raise self.retry(exc=exc, countdown=15)


# ---------------------------------------------------------------------------
# post_miro_document
# ---------------------------------------------------------------------------


async def _run_miro_posting(task: Task, document_id: str, posted_by: str) -> None:
    from src.database import AsyncSessionLocal
    from src.models.document import DocumentStatus, MIROStatus
    from src.repositories.document_repository import DocumentRepository
    from src.services.miro_service import build_miro_payload
    from src.services.sap_service import get_sap_service
    from src.utils.audit import MIRO_FAILED, MIRO_POSTED, log_action
    from src.utils.redis_client import connect_redis, get_redis

    await connect_redis()
    redis = get_redis()
    bound_log = log.bind(document_id=document_id, task_id=task.request.id)

    async with AsyncSessionLocal() as session:
        doc_repo = DocumentRepository(session)
        try:
            doc = await doc_repo.find_by_document_id(document_id)
            if not doc:
                bound_log.error("document not found — MIRO posting aborted")
                return

            doc_id = doc["id"]
            extracted: dict[str, Any] = doc.get("extracted") or {}
            sap_validation: dict[str, Any] = doc.get("sap_validation") or {}
            po_number: str = extracted.get("po_number") or ""

            await doc_repo.update_status(doc_id, DocumentStatus.POSTING)
            await session.commit()

            from src.schemas.sap import SAPPOResponse
            sap_service = get_sap_service()
            sap_po = await sap_service.fetch_po_details(po_number) if po_number else SAPPOResponse()
            payload = build_miro_payload(extracted, sap_po, sap_validation)
            miro_resp = await sap_service.post_miro(payload)

            posting_data: dict[str, Any] = {
                "posted_at":    datetime.now(UTC).isoformat(),
                "payload_sent": payload.model_dump(),
                "miro_number":  miro_resp.miro_number,
                "sap_response": miro_resp.sap_response,
                "status":       MIROStatus.SUCCESS.value if miro_resp.success else MIROStatus.FAILED.value,
            }
            await doc_repo.update_miro_posting(doc_id, posting_data)
            await session.commit()

            stream_name = "document:posted" if miro_resp.success else "document:post_failed"
            await redis.xadd(stream_name, {
                "document_id": document_id,
                "miro_number": miro_resp.miro_number,
                "status":      miro_resp.status,
                "timestamp":   datetime.now(UTC).isoformat(),
            })

            action = MIRO_POSTED if miro_resp.success else MIRO_FAILED
            await log_action(document_id, action, posted_by,
                             {"miro_number": miro_resp.miro_number, "status": miro_resp.status})

        except Exception as exc:
            bound_log.error("MIRO posting failed", error=str(exc), attempt=task.request.retries)
            error_entry: dict[str, Any] = {
                "stage": "miro_posting", "message": str(exc),
                "detail": type(exc).__name__, "timestamp": datetime.now(UTC).isoformat(),
            }
            doc2 = await doc_repo.find_by_document_id(document_id)
            if doc2:
                new_status = DocumentStatus.FAILED if task.request.retries >= task.max_retries else DocumentStatus.VALIDATED
                await doc_repo.update_status(doc2["id"], new_status, error_entry=error_entry)
                await session.commit()
            raise


@celery_app.task(name="post_miro_document", bind=True, max_retries=3, default_retry_delay=15)
def post_miro_document(self: Task, document_id: str, posted_by: str = "system") -> None:
    try:
        asyncio.run(_run_miro_posting(self, document_id, posted_by))
    except Exception as exc:
        raise self.retry(exc=exc, countdown=15 * (2 ** self.request.retries))


# ---------------------------------------------------------------------------
# Direct async validation — used when Celery is not running
# ---------------------------------------------------------------------------


async def run_validation_direct(document_id: str) -> None:
    """Run SAP validation directly — routes to Service PO or Material PO based on invoice_subtype."""
    from src.database import AsyncSessionLocal
    from src.models.document import DocumentStatus, InvoiceSubtype
    from src.repositories.document_repository import DocumentRepository
    from src.services.sap_service import get_sap_service
    from src.services.validation_service import validate_invoice_against_po, validate_service_invoice_against_po

    bound_log = log.bind(document_id=document_id)

    async with AsyncSessionLocal() as session:
        doc_repo = DocumentRepository(session)
        try:
            doc = await doc_repo.find_by_document_id(document_id)
            if not doc:
                bound_log.error("document not found — validation aborted")
                return

            doc_id = doc["id"]
            extracted: dict[str, Any] = doc.get("extracted") or {}
            invoice_subtype: str = doc.get("invoice_subtype") or ""
            is_freight_po = invoice_subtype == InvoiceSubtype.FREIGHT_PO
            is_service_po = invoice_subtype == InvoiceSubtype.SERVICE_PO
            po_number: str = extracted.get("po_number") or ""

            if not po_number:
                await doc_repo.update_status(doc_id, DocumentStatus.FAILED, error_entry={
                    "stage": "validation", "message": "No PO number found in extracted data",
                    "detail": "MISSING_PO_NUMBER", "timestamp": datetime.now(UTC).isoformat(),
                })
                await session.commit()
                return

            await doc_repo.update_status(doc_id, DocumentStatus.VALIDATING)
            await session.commit()

            sap_service = get_sap_service()

            try:
                if is_service_po:
                    sap_spo = await sap_service.fetch_service_po_details(po_number)
                    if not sap_spo.ses_approved:
                        await doc_repo.update_status(doc_id, DocumentStatus.FAILED, error_entry={
                            "stage": "validation",
                            "message": "Service Entry Sheet (SES) not yet approved in SAP.",
                            "detail": "SES_NOT_APPROVED", "timestamp": datetime.now(UTC).isoformat(),
                        })
                        await session.commit()
                        return
                    validation_result = await validate_service_invoice_against_po(extracted, sap_spo)
                else:
                    sap_po = await sap_service.fetch_po_details(po_number)
                    validation_result = await validate_invoice_against_po(extracted, sap_po)
            except Exception as sap_exc:
                bound_log.error("SAP fetch failed — aborting validation", error=str(sap_exc))
                await doc_repo.update_status(doc_id, DocumentStatus.FAILED, error_entry={
                    "stage": "sap_fetch", "message": str(sap_exc),
                    "detail": type(sap_exc).__name__, "timestamp": datetime.now(UTC).isoformat(),
                })
                await session.commit()
                return

            is_valid: bool = bool(validation_result.get("is_valid", False))
            await doc_repo.update_sap_validation(doc_id, validation_result, is_valid=is_valid)
            await session.commit()
            bound_log.info("direct validation complete",
                           overall=validation_result.get("overall_confidence"),
                           is_valid=is_valid)

        except Exception as exc:
            bound_log.error("direct validation failed", error=str(exc))
            error_entry: dict[str, Any] = {
                "stage": "validation", "message": str(exc),
                "detail": type(exc).__name__, "timestamp": datetime.now(UTC).isoformat(),
            }
            try:
                doc2 = await doc_repo.find_by_document_id(document_id)
                if doc2:
                    await doc_repo.update_status(doc2["id"], DocumentStatus.FAILED, error_entry=error_entry)
                    await session.commit()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Direct async MIRO posting — used when Celery is not running
# ---------------------------------------------------------------------------


async def run_miro_direct(document_id: str, posted_by: str = "system") -> None:
    """Run MIRO posting directly — routes to Service/Freight/Material MIRO."""
    import traceback as _tb
    from src.database import AsyncSessionLocal
    from src.models.document import DocumentStatus, InvoiceSubtype, MIROStatus
    from src.repositories.document_repository import DocumentRepository
    from src.services.miro_service import build_freight_miro_payload, build_miro_payload, build_service_miro_payload
    from src.services.sap_service import get_sap_service
    from src.schemas.sap import SAPPOResponse, SAPServicePOResponse

    bound_log = log.bind(document_id=document_id)
    bound_log.info("run_miro_direct entered")

    async with AsyncSessionLocal() as session:
        doc_repo = DocumentRepository(session)
        try:
            doc = await doc_repo.find_by_document_id(document_id)
            if not doc:
                bound_log.error("document not found — MIRO posting aborted")
                return

            doc_id = doc["id"]
            extracted: dict[str, Any] = doc.get("extracted") or {}
            sap_validation: dict[str, Any] = doc.get("sap_validation") or {}
            po_number: str = extracted.get("po_number") or ""
            invoice_subtype: str = doc.get("invoice_subtype") or ""
            is_freight_po = invoice_subtype == InvoiceSubtype.FREIGHT_PO
            is_service_po = invoice_subtype == InvoiceSubtype.SERVICE_PO

            await doc_repo.update_status(doc_id, DocumentStatus.POSTING)
            await session.commit()

            sap_service = get_sap_service()

            if is_service_po:
                sap_spo = await sap_service.fetch_service_po_details(po_number) if po_number else SAPServicePOResponse()
                payload = build_service_miro_payload(extracted, sap_spo, sap_validation)
                miro_resp = await sap_service.post_service_miro(payload)
            elif is_freight_po:
                sap_po = await sap_service.fetch_po_details(po_number) if po_number else SAPPOResponse()
                payload = build_freight_miro_payload(extracted, sap_po, sap_validation)
                miro_resp = await sap_service.post_service_miro(payload)
            else:
                sap_po = await sap_service.fetch_po_details(po_number) if po_number else SAPPOResponse()
                payload = build_miro_payload(extracted, sap_po, sap_validation)
                miro_resp = await sap_service.post_miro(payload)

            posting_data: dict[str, Any] = {
                "posted_at":    datetime.now(UTC).isoformat(),
                "payload_sent": payload.model_dump(),
                "miro_number":  miro_resp.miro_number,
                "sap_response": miro_resp.sap_response,
                "status":       MIROStatus.SUCCESS.value if miro_resp.success else MIROStatus.FAILED.value,
            }
            await doc_repo.update_miro_posting(doc_id, posting_data)
            await session.commit()
            bound_log.info("MIRO posting complete", miro_number=miro_resp.miro_number)

        except Exception as exc:
            bound_log.error("direct MIRO posting failed", error=str(exc), traceback=_tb.format_exc())
            error_entry: dict[str, Any] = {
                "stage": "miro_posting", "message": str(exc) or type(exc).__name__,
                "detail": type(exc).__name__, "timestamp": datetime.now(UTC).isoformat(),
            }
            try:
                doc2 = await doc_repo.find_by_document_id(document_id)
                if doc2:
                    await doc_repo.update_status(doc2["id"], DocumentStatus.VALIDATED, error_entry=error_entry)
                    await session.commit()
            except Exception:
                pass
