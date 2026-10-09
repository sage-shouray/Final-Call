"""MIGO worker — posts GRN to SAP."""
from __future__ import annotations

from datetime import UTC, datetime

import structlog

log = structlog.get_logger(__name__)


async def run_migo_103_direct(document_id: str) -> None:
    """Sangam's quality-hold workflow: auto-GRN into blocked stock (movement 103).

    Runs unattended, right after routing resolves a PO — no manager click, since
    Sangam's own process has a person (quality) in the loop later, not here.
    This stands in for a real per-tenant workflow-profile system: today it is
    the only automated step of Sangam's flow that's built, so the pipeline calls
    it directly rather than through a profile registry that doesn't exist yet.
    The document is left at GR_POSTED — "received, not yet invoiced" is accurate
    whether or not SAP calls the stock blocked; a distinct "awaiting quality
    release" status is the next piece, once the SAP notification endpoint exists.
    """
    import traceback as _tb
    from src.database import AsyncSessionLocal
    from src.models.document import DocumentStatus, GRNStatus
    from src.repositories.document_repository import DocumentRepository
    from src.schemas.sap import SAPPOResponse
    from src.services.grn_service import build_grn_103_payload
    from src.services.sap_service import get_sap_service

    bound_log = log.bind(document_id=document_id)
    bound_log.info("run_migo_103_direct entered")

    async with AsyncSessionLocal() as session:
        doc_repo = DocumentRepository(session)
        try:
            doc = await doc_repo.find_by_document_id(document_id)
            if not doc:
                bound_log.error("document not found — GRN-103 posting aborted")
                return

            if (doc.get("grn_posting") or {}).get("status") == GRNStatus.SUCCESS.value:
                bound_log.info("GRN already posted for this document — skipping")
                return

            doc_id = doc["id"]
            extracted = doc.get("extracted") or {}
            po_number = extracted.get("po_number") or (doc.get("pipeline") or {}).get("routing", {}).get("po_number") or ""
            if not po_number:
                bound_log.warning("no PO number yet — cannot post GRN-103")
                return
            bound_log.info("document loaded", doc_id=doc_id, po_number=po_number)

            sap_service = get_sap_service(doc.get("tenant_id"))
            sap_po = await sap_service.fetch_po_details(po_number)
            bound_log.info("SAP PO fetched", line_count=len(sap_po.PO_LINE_ITEMS))
            if not sap_po.PO_LINE_ITEMS:
                bound_log.warning("PO has no line items — cannot post GRN-103")
                return

            grn_payload = build_grn_103_payload(extracted, sap_po)
            grn_resp = await sap_service.post_grn_103(grn_payload)
            bound_log.info("GRN-103 response received", grn_number=grn_resp.grn_number, success=grn_resp.success)

            grn_posting_data = {
                "posted_at":    datetime.now(UTC).isoformat(),
                "payload_sent": grn_payload.model_dump(),
                "grn_number":   grn_resp.grn_number,
                "sap_response": grn_resp.sap_response,
                "status":       GRNStatus.SUCCESS.value if grn_resp.success else GRNStatus.FAILED.value,
                "already_done": grn_resp.already_done,
                "message":      grn_resp.message,
                "movement_type": "103",
                "pending_quality_release": grn_resp.success,
            }
            await doc_repo.update_grn_posting(doc_id, grn_posting_data)
            if grn_resp.success:
                await doc_repo.update_status(doc_id, DocumentStatus.GR_POSTED)
            await session.commit()
            bound_log.info("GRN-103 posting saved", grn_number=grn_resp.grn_number)

        except Exception as exc:
            bound_log.error("GRN-103 posting failed", error=str(exc), traceback=_tb.format_exc())
            try:
                doc2 = await doc_repo.find_by_document_id(document_id)
                if doc2:
                    await doc_repo.update_status(doc2["id"], doc2["status"], error_entry={
                        "stage": "migo_103", "message": str(exc) or type(exc).__name__,
                        "detail": type(exc).__name__, "timestamp": datetime.now(UTC).isoformat(),
                    })
                    await session.commit()
            except Exception:
                pass


async def run_migo_direct(document_id: str, posted_by: str = "system") -> None:
    import traceback as _tb
    from src.database import AsyncSessionLocal
    from src.models.document import DocumentStatus, GRNStatus
    from src.repositories.document_repository import DocumentRepository
    from src.schemas.sap import SAPPOResponse
    from src.services.grn_service import build_grn_payload
    from src.services.sap_service import get_sap_service

    bound_log = log.bind(document_id=document_id)
    bound_log.info("run_migo_direct entered")

    async with AsyncSessionLocal() as session:
        doc_repo = DocumentRepository(session)
        try:
            doc = await doc_repo.find_by_document_id(document_id)
            if not doc:
                bound_log.error("document not found — MIGO posting aborted")
                return

            # Last line of defence. The HTTP endpoints check this too, but the
            # rule is about the data rather than about who asked, so it is
            # enforced where the posting actually happens — a future caller,
            # retry or queued task cannot route around it.
            from src.services.autopost_service import blocking_failures
            _mismatch = await blocking_failures(doc)
            if _mismatch:
                _why = " ".join(f["detail"] for f in _mismatch if f.get("detail"))
                bound_log.error(
                    "posting refused — invoice does not match SAP",
                    failed_gates=[f["gate"] for f in _mismatch],
                )
                await doc_repo.update_status(
                    doc["id"], DocumentStatus.FAILED,
                    error_entry={"stage": "migo",
                                 "error": f"Invoice does not match the purchase order in SAP. {_why}"},
                )
                await session.commit()
                return

            doc_id = doc["id"]
            extracted = doc.get("extracted") or {}
            po_number = extracted.get("po_number") or ""
            bound_log.info("document loaded", doc_id=doc_id, po_number=po_number)

            await doc_repo.update_status(doc_id, DocumentStatus.GR_POSTING)
            await session.commit()

            sap_service = get_sap_service(doc.get("tenant_id"))
            sap_po = await sap_service.fetch_po_details(po_number) if po_number else SAPPOResponse()
            bound_log.info("SAP PO fetched", line_count=len(sap_po.PO_LINE_ITEMS))

            grn_payload = build_grn_payload(extracted, sap_po)
            grn_resp = await sap_service.post_grn(grn_payload)
            bound_log.info("GRN response received", grn_number=grn_resp.grn_number, success=grn_resp.success)

            grn_posting_data = {
                "posted_at":    datetime.now(UTC).isoformat(),
                "payload_sent": grn_payload.model_dump(),
                "grn_number":   grn_resp.grn_number,
                "sap_response": grn_resp.sap_response,
                "item_data":    grn_resp.sap_response.get("ITEM_DATA", []),
                "status":       GRNStatus.SUCCESS.value if grn_resp.success else GRNStatus.FAILED.value,
                "already_done": grn_resp.already_done,
                "message":      grn_resp.message,
            }
            await doc_repo.update_grn_posting(doc_id, grn_posting_data)
            await session.commit()
            bound_log.info("GRN posting saved", grn_number=grn_resp.grn_number)

            if not grn_resp.success:
                bound_log.warning("GRN posting failed — stopping", message=grn_resp.message)
                return

            bound_log.info("GRN complete — waiting for user to post MIRO", grn_number=grn_resp.grn_number)

        except Exception as exc:
            bound_log.error("MIGO posting failed", error=str(exc), traceback=_tb.format_exc())
            error_entry = {
                "stage": "migo_posting", "message": str(exc) or type(exc).__name__,
                "detail": type(exc).__name__, "timestamp": datetime.now(UTC).isoformat(),
            }
            try:
                doc2 = await doc_repo.find_by_document_id(document_id)
                if doc2:
                    await doc_repo.update_status(doc2["id"], DocumentStatus.VALIDATED, error_entry=error_entry)
                    await session.commit()
            except Exception:
                pass
