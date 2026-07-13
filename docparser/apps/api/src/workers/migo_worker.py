"""MIGO worker — posts GRN to SAP."""
from __future__ import annotations

from datetime import UTC, datetime

import structlog

log = structlog.get_logger(__name__)


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

            doc_id = doc["id"]
            extracted = doc.get("extracted") or {}
            po_number = extracted.get("po_number") or ""
            bound_log.info("document loaded", doc_id=doc_id, po_number=po_number)

            await doc_repo.update_status(doc_id, DocumentStatus.GR_POSTING)
            await session.commit()

            sap_service = get_sap_service()
            sap_po = await sap_service.fetch_po_details(po_number) if po_number else SAPPOResponse()
            bound_log.info("SAP PO fetched", line_count=len(sap_po.PO_LINE_ITEMS))

            grn_payload = build_grn_payload(extracted, sap_po)
            grn_resp = await sap_service.post_grn(grn_payload)
            bound_log.info("GRN response received", grn_number=grn_resp.grn_number, success=grn_resp.success)

            grn_posting_data = {
                "posted_at":    datetime.now(UTC),
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
