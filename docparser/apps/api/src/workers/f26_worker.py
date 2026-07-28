"""F-26 worker — simulates and posts customer payment via ZINV_PAY/INV_PAYMENT."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog

log = structlog.get_logger(__name__)


def _to_dot_date(value: str) -> str:
    """SAP's F-26 API expects DD.MM.YYYY. Extracted/typed dates commonly arrive
    as DD-MM-YYYY or DD/MM/YYYY — normalise separators to dots; leave already-dotted
    or malformed values untouched."""
    value = (value or "").strip()
    if not value:
        return ""
    return value.replace("/", ".").replace("-", ".")


def _build_f26_payload(
    extracted: dict[str, Any], indicator: str, form_data: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Map form fields (preferred) or OCR-extracted fields (fallback) to the F26 API payload."""
    form = form_data or {}

    def pick(*keys: str, default: str = "") -> str:
        for key in keys:
            val = form.get(key)
            if val not in (None, ""):
                return str(val)
        for key in keys:
            val = extracted.get(key)
            if val not in (None, ""):
                return str(val)
        return default

    invoice_date_fallback = extracted.get("invoice_date", "")

    return {
        "company_code":  pick("company_code"),
        "customer":      pick("customer"),
        "invoice":       pick("invoice", "invoice_no"),
        "fiscal_year":   pick("fiscal_year"),
        "document_date": _to_dot_date(pick("document_date", default=invoice_date_fallback)),
        "posting_date":  _to_dot_date(pick("posting_date", default=invoice_date_fallback)),
        "currency":      pick("currency", default=extracted.get("currency", "INR")),
        "amount":        pick("amount", "gross_amount"),
        "bank_gl":       pick("bank_gl"),
        "value_date":    _to_dot_date(pick("value_date", default=invoice_date_fallback)),
        "reference":     pick("reference", "reference_doc", default=extracted.get("invoice_no", "")),
        "header_text":   pick("header_text", default="Customer Payment"),
        "item_text":     pick("item_text", default="Payment against Invoice"),
        "indicator":     indicator,
    }


async def run_f26_simulate(
    document_id: str, posted_by: str = "system", form_data: dict[str, Any] | None = None
) -> None:
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

            payload_dict = _build_f26_payload(extracted, indicator="X", form_data=form_data)
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

            # Reuse the exact fields sent during simulation (indicator swapped to post)
            sim_payload = sim.get("payload_sent") or {}
            payload_dict = _build_f26_payload(extracted, indicator="", form_data=sim_payload)
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
