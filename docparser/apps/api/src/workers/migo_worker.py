"""MIGO worker — posts GRN to SAP, then posts MIRO against that GRN."""
from __future__ import annotations

from datetime import UTC, datetime

import structlog

log = structlog.get_logger(__name__)


async def run_migo_direct(document_id: str, posted_by: str = "system") -> None:
    import traceback as _tb

    from src.database import get_database
    from src.models.document import DocumentStatus, GRNStatus
    from src.repositories.document_repository import DocumentRepository
    from src.schemas.sap import SAPPOResponse
    from src.services.grn_service import build_grn_payload
    from src.services.sap_service import get_sap_service

    bound_log = log.bind(document_id=document_id)
    bound_log.info("run_migo_direct entered")

    try:
        db = get_database()
        doc_repo = DocumentRepository(db)
        doc = await doc_repo.find_by_document_id(document_id)
        if not doc:
            bound_log.error("document not found — MIGO posting aborted")
            return

        mongo_id = str(doc["_id"])
        extracted = doc.get("extracted") or {}
        sap_validation = doc.get("sap_validation") or {}
        po_number = extracted.get("po_number") or ""
        bound_log.info("document loaded", mongo_id=mongo_id, po_number=po_number)

        # ── Step 1: Set status to GR_POSTING ──────────────────────────────────
        await doc_repo.update_status(mongo_id, DocumentStatus.GR_POSTING)
        bound_log.info("status set to GR_POSTING")

        # ── Step 2: Fetch SAP PO details ──────────────────────────────────────
        sap_service = get_sap_service()
        bound_log.info("fetching SAP PO", po_number=po_number)
        sap_po = await sap_service.fetch_po_details(po_number) if po_number else SAPPOResponse()
        bound_log.info("SAP PO fetched", line_count=len(sap_po.PO_LINE_ITEMS))

        # ── Step 3: Build and post GRN ────────────────────────────────────────
        grn_payload = build_grn_payload(extracted, sap_po)
        bound_log.info("GRN payload built", lines=len(grn_payload.po_items))

        grn_resp = await sap_service.post_grn(grn_payload)
        bound_log.info("GRN response received", grn_number=grn_resp.grn_number, success=grn_resp.success)

        grn_posting_data = {
            "posted_at": datetime.now(UTC),
            "payload_sent": grn_payload.model_dump(),
            "grn_number": grn_resp.grn_number,
            "sap_response": grn_resp.sap_response,
            "item_data": grn_resp.sap_response.get("ITEM_DATA", []),
            "status": GRNStatus.SUCCESS.value if grn_resp.success else GRNStatus.FAILED.value,
            "already_done": grn_resp.already_done,
            "message": grn_resp.message,
        }
        await doc_repo.update_grn_posting(mongo_id, grn_posting_data)
        bound_log.info("GRN posting saved", grn_number=grn_resp.grn_number, success=grn_resp.success)

        if not grn_resp.success:
            bound_log.warning("GRN posting failed — skipping MIRO", message=grn_resp.message)
            return

        # GRN done — stop here. User will review GRN data and manually click "Post to MIRO"
        bound_log.info("GRN complete — waiting for user to post MIRO", grn_number=grn_resp.grn_number)

    except Exception as exc:
        bound_log.error(
            "MIGO posting failed",
            error=str(exc),
            exc_type=type(exc).__name__,
            traceback=_tb.format_exc(),
        )
        error_entry = {
            "stage": "migo_posting",
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
                    DocumentStatus.VALIDATED,
                    error_entry=error_entry,
                )
        except Exception:
            pass
