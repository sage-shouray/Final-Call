"""FB60 worker — posts Non-PO invoice to SAP FB60."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog

log = structlog.get_logger(__name__)


async def run_fb60_direct(document_id: str, form_data: dict[str, Any], posted_by: str = "system") -> None:
    import traceback as _tb

    from src.database import get_database
    from src.models.document import DocumentStatus, FB60Status
    from src.repositories.document_repository import DocumentRepository
    from src.services.fb60_service import build_fb60_payload
    from src.services.sap_service import get_sap_service

    bound_log = log.bind(document_id=document_id)
    bound_log.info("run_fb60_direct entered")

    try:
        db = get_database()
        doc_repo = DocumentRepository(db)
        doc = await doc_repo.find_by_document_id(document_id)
        if not doc:
            bound_log.error("document not found — FB60 posting aborted")
            return

        mongo_id = str(doc["_id"])

        await doc_repo.update_status(mongo_id, DocumentStatus.POSTING)
        bound_log.info("status set to POSTING")

        payload = build_fb60_payload(form_data)
        bound_log.info("FB60 payload built", line_count=len(payload.data[0].Invoice_Items))

        sap_service = get_sap_service()
        fb60_resp = await sap_service.post_fb60(payload)
        bound_log.info("FB60 response received", fb60_number=fb60_resp.fb60_number, success=fb60_resp.success)

        posting_data = {
            "posted_at": datetime.now(UTC),
            "payload_sent": payload.model_dump(),
            "fb60_number": fb60_resp.fb60_number,
            "sap_response": fb60_resp.sap_response,
            "message": fb60_resp.message,
            "status": FB60Status.SUCCESS.value if fb60_resp.success else FB60Status.FAILED.value,
        }
        await doc_repo.update_fb60_posting(mongo_id, posting_data)
        bound_log.info("FB60 posting saved", fb60_number=fb60_resp.fb60_number, success=fb60_resp.success)

    except Exception as exc:
        bound_log.error(
            "FB60 posting failed",
            error=str(exc),
            exc_type=type(exc).__name__,
            traceback=_tb.format_exc(),
        )
        error_entry = {
            "stage": "fb60_posting",
            "message": str(exc) or type(exc).__name__,
            "detail": type(exc).__name__,
            "timestamp": datetime.now(UTC),
        }
        try:
            db2 = get_database()
            doc2 = await DocumentRepository(db2).find_by_document_id(document_id)
            if doc2:
                await DocumentRepository(db2).update_status(
                    str(doc2["_id"]),
                    DocumentStatus.EXTRACTED,
                    error_entry=error_entry,
                )
        except Exception:
            pass
