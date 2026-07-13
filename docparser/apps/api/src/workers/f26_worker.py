"""F-26 worker — simulates and posts customer payment via ZINV_PAY/INV_PAYMENT."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog

log = structlog.get_logger(__name__)


def _build_f26_payload(extracted: dict[str, Any], indicator: str) -> dict[str, Any]:
    """Map OCR-extracted fields to F26 API payload."""
    return {
        "company_code":  extracted.get("company_code", ""),
        "customer":      extracted.get("customer", ""),
        "invoice":       extracted.get("invoice_no", ""),
        "fiscal_year":   extracted.get("fiscal_year", ""),
        "document_date": extracted.get("document_date") or extracted.get("invoice_date", ""),
        "posting_date":  extracted.get("posting_date") or extracted.get("invoice_date", ""),
        "currency":      extracted.get("currency", "INR"),
        "amount":        str(extracted.get("gross_amount") or extracted.get("amount", "")),
        "bank_gl":       extracted.get("bank_gl", ""),
        "value_date":    extracted.get("value_date") or extracted.get("invoice_date", ""),
        "reference":     extracted.get("reference") or extracted.get("reference_doc", ""),
        "header_text":   extracted.get("header_text", "Customer Payment"),
        "item_text":     extracted.get("item_text", "Payment against Invoice"),
        "indicator":     indicator,
    }


async def run_f26_simulate(document_id: str, posted_by: str = "system") -> None:
    """Run F-26 simulation (indicator='X') and save result."""
    from src.database import AsyncSessionLocal
    from src.models.document import DocumentStatus
    from src.repositories.document_repository import DocumentRepository
    from src.schemas.sap import F26Payload
    from src.services.sap_service import get_sap_service

    bound_log = log.bind(document_id=document_id)

    async with AsyncSessionLocal() as session:
        doc_repo = DocumentRepository(session)
        try:
            doc = await doc_repo.find_by_document_id(document_id)
            if not doc:
                bound_log.error("document not found — F26 simulation aborted")
                return

            doc_id = doc["id"]
            extracted: dict[str, Any] = doc.get("extracted") or {}

            await doc_repo.update_status(doc_id, DocumentStatus.SIMULATING)
            await session.commit()

            payload_dict = _build_f26_payload(extracted, indicator="X")
            payload = F26Payload(**payload_dict)

            sap_service = get_sap_service()
            resp = await sap_service.call_f26(payload)

            sim_data: dict[str, Any] = {
                "simulated_at":  datetime.now(UTC).isoformat(),
                "payload_sent":  payload_dict,
                "status":        "STATUS" in resp.model_fields and resp.STATUS or resp.STATUS,
                "message":       resp.MESSAGE,
                "success":       resp.success,
                "sap_response":  resp.sap_response,
            }

            if resp.success:
                await doc_repo.update_f26_simulation(doc_id, sim_data)
                bound_log.info("F26 simulation successful", message=resp.MESSAGE)
            else:
                sim_data["status"] = "failed"
                await doc_repo.update(doc_id, {"f26_simulation": sim_data, "status": DocumentStatus.FAILED.value})
            await session.commit()

        except Exception as exc:
            bound_log.error("F26 simulation failed", error=str(exc))
            err: dict[str, Any] = {
                "stage": "f26_simulation", "message": str(exc),
                "detail": type(exc).__name__, "timestamp": datetime.now(UTC).isoformat(),
            }
            try:
                doc2 = await doc_repo.find_by_document_id(document_id)
                if doc2:
                    await doc_repo.update_status(doc2["id"], DocumentStatus.FAILED, error_entry=err)
                    await session.commit()
            except Exception:
                pass


async def run_f26_post(document_id: str, posted_by: str = "system") -> str:
    """Post a previously simulated F-26 payment (indicator='') and return document number."""
    from src.database import AsyncSessionLocal
    from src.models.document import DocumentStatus
    from src.repositories.document_repository import DocumentRepository
    from src.schemas.sap import F26Payload
    from src.services.sap_service import get_sap_service

    bound_log = log.bind(document_id=document_id)

    async with AsyncSessionLocal() as session:
        doc_repo = DocumentRepository(session)
        try:
            doc = await doc_repo.find_by_document_id(document_id)
            if not doc:
                bound_log.error("document not found — F26 posting aborted")
                return ""

            doc_id = doc["id"]
            extracted: dict[str, Any] = doc.get("extracted") or {}

            # Must have a successful simulation first
            sim = doc.get("f26_simulation") or {}
            if not sim.get("success"):
                bound_log.error("F26 posting aborted — no successful simulation found")
                raise ValueError("Cannot post F-26: no successful simulation on record.")

            await doc_repo.update_status(doc_id, DocumentStatus.POSTING)
            await session.commit()

            # Use the same payload as simulation but with indicator=""
            payload_dict = _build_f26_payload(extracted, indicator="")
            payload = F26Payload(**payload_dict)

            sap_service = get_sap_service()
            resp = await sap_service.call_f26(payload)

            posting_data: dict[str, Any] = {
                "posted_at":       datetime.now(UTC).isoformat(),
                "payload_sent":    payload_dict,
                "document_number": resp.DOCUMENT_NUMBER,
                "message":         resp.MESSAGE,
                "status":          "success" if resp.success else "failed",
                "sap_response":    resp.sap_response,
            }

            await doc_repo.update_f26_posting(doc_id, posting_data)
            await session.commit()

            if resp.success:
                bound_log.info("F26 posted successfully", document_number=resp.DOCUMENT_NUMBER)
            else:
                bound_log.error("F26 posting failed", message=resp.MESSAGE)

            return resp.DOCUMENT_NUMBER

        except Exception as exc:
            bound_log.error("F26 posting failed unexpectedly", error=str(exc))
            err: dict[str, Any] = {
                "stage": "f26_posting", "message": str(exc),
                "detail": type(exc).__name__, "timestamp": datetime.now(UTC).isoformat(),
            }
            try:
                doc2 = await doc_repo.find_by_document_id(document_id)
                if doc2:
                    await doc_repo.update_status(doc2["id"], DocumentStatus.SIMULATED, error_entry=err)
                    await session.commit()
            except Exception:
                pass
            return ""
