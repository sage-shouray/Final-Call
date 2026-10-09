"""Document endpoints — upload, status polling, presigned URL, SAP integration."""
import math
import random
from datetime import UTC, datetime
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Form, Query, UploadFile

from src.database import AsyncSessionLocal
from src.exceptions import NotFoundError, ValidationError
from src.middleware.auth import CurrentUser, require_role
from src.models.document import TCODE_MAP, DocumentStatus, DocumentType, InvoiceSubtype
from src.repositories.document_repository import DocumentRepository
from src.schemas.documents import (
    CreditComparisonResponse,
    DocumentListItem,
    DocumentListResponse,
    DocumentResponse,
    DocumentUploadResponse,
    F26PostTriggerResponse,
    F26SimulateTriggerResponse,
    FB60TriggerResponse,
    GRNTriggerResponse,
    MIROParkTriggerResponse,
    MIROTriggerResponse,
    PresignedUrlResponse,
    ValidationResultResponse,
    ValidationTriggerResponse,
)
from src.schemas.sap import MIRODetailResponse
from src.services.storage_service import (
    build_s3_key,
    get_presigned_url,
    upload_file,
    validate_upload,
)
from src.utils.redis_client import get_redis
from src.utils.serializer import serialize_doc
from src.exceptions import AuthError as _AuthError

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/documents", tags=["Documents"])


def _tenant_ok(doc: dict, current_user) -> bool:
    """Return True if the current user is allowed to access this document."""
    if current_user.role == "admin" and not getattr(current_user, "tenant_id", None):
        return True
    doc_tenant = doc.get("tenant_id")
    user_tenant = getattr(current_user, "tenant_id", None)
    return doc_tenant is None or doc_tenant == user_tenant


def _assert_tenant(doc: dict, current_user) -> None:
    if not _tenant_ok(doc, current_user):
        raise _AuthError(
            "You do not have permission to access this document",
            error_code="FORBIDDEN",
            status_code=403,
        )


async def _write_doc_audit(
    *,
    action: str,
    document_id: str,
    performed_by: str,
    details: dict | None = None,
) -> None:
    try:
        from src.database import AsyncSessionLocal as _Sess
        from src.models.audit_log import AuditLogRow
        async with _Sess() as _s:
            _s.add(AuditLogRow(
                document_id=document_id,
                action=action,
                performed_by=performed_by,
                ip_address="",
                details=details or {},
            ))
            await _s.commit()
    except Exception as _exc:
        log.warning("doc audit log write failed", error=str(_exc))


def _generate_document_id() -> str:
    year = datetime.now(UTC).year
    suffix = str(random.randint(100_000, 999_999))
    return f"DOC-{year}-{suffix}"


# ---------------------------------------------------------------------------
# POST /api/documents/upload
# ---------------------------------------------------------------------------

@router.post("/upload", response_model=DocumentUploadResponse, status_code=202)
async def upload_document(
    current_user: CurrentUser,
    file: UploadFile,
    document_type: str = Form(...),
    invoice_subtype: str = Form(default=""),
) -> DocumentUploadResponse:
    """Accept a document from the web UI.

    The work happens in ingestion_service, which the mailbox poller also calls —
    so a document behaves identically however it arrived.
    """
    from src.services.ingestion_service import IngestSource, ingest_document

    try:
        doc_type = DocumentType(document_type)
    except ValueError:
        raise ValidationError(
            f"Invalid document_type '{document_type}'. Allowed: {[t.value for t in DocumentType]}",
            error_code="INVALID_DOCUMENT_TYPE",
        )

    parsed_subtype: InvoiceSubtype | None = None
    if invoice_subtype:
        try:
            parsed_subtype = InvoiceSubtype(invoice_subtype)
        except ValueError:
            pass

    file_bytes = await file.read()
    result = await ingest_document(
        file_bytes=file_bytes,
        filename=file.filename or "upload",
        content_type=file.content_type or "application/octet-stream",
        document_type=doc_type,
        invoice_subtype=parsed_subtype,
        tenant_id=getattr(current_user, "tenant_id", None),
        source=IngestSource(channel="web", actor=current_user.sub),
        # A person re-uploading knows what they are doing; the duplicate is
        # reported by the auto-post gate rather than refused here.
        reject_duplicates=False,
    )

    try:
        await get_redis().xadd("document:uploaded", {
            "document_id": result.document_id,
            "row_id":      result.row_id,
            "uploaded_by": current_user.sub,
            "timestamp":   datetime.now(UTC).isoformat(),
        })
    except Exception as exc:
        log.warning("Redis stream publish failed", error=str(exc), document_id=result.document_id)

    import asyncio as _asyncio
    _asyncio.create_task(_write_doc_audit(
        action="document.uploaded",
        document_id=result.document_id,
        performed_by=current_user.sub,
        details={"type": doc_type.value, "filename": file.filename, "size": len(file_bytes)},
    ))

    message = "Document uploaded successfully. Extraction started in the background."
    if result.split_document_ids:
        all_ids = [result.document_id, *result.split_document_ids]
        message = (
            f"This PDF contained {len(all_ids)} invoices and was split into "
            f"separate documents: {', '.join(all_ids)}."
        )
    elif result.duplicate_of:
        message = f"Uploaded. Note: an identical file was already processed as {result.duplicate_of}."

    return DocumentUploadResponse(
        document_id=result.document_id, status="processing", message=message,
    )


# ---------------------------------------------------------------------------
# GET /api/documents
# ---------------------------------------------------------------------------

@router.get("", response_model=DocumentListResponse)
async def list_documents(
    current_user: CurrentUser,
    status: str | None = Query(default=None),
    type: str | None = Query(default=None),
    tcode: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None),
) -> DocumentListResponse:
    filter_query: dict[str, Any] = {}

    if status:
        filter_query["status"] = status
    if type:
        filter_query["type"] = type
    if tcode:
        filter_query["tcode"] = tcode
    if current_user.role == "operator":
        filter_query["uploaded_by"] = current_user.sub

    # Tenant isolation — non-super-admin users only see their company's documents
    user_tenant = getattr(current_user, "tenant_id", None)
    if user_tenant:
        filter_query["tenant_id"] = user_tenant

    skip = (page - 1) * limit

    async with AsyncSessionLocal() as session:
        repo = DocumentRepository(session)
        if search:
            docs, total = await repo.search_documents(search, filter_query, skip=skip, limit=limit)
        else:
            docs, total = await repo.list_documents(filter_query=filter_query, skip=skip, limit=limit)

    items: list[DocumentListItem] = []
    for doc in docs:
        safe = serialize_doc(doc)
        extracted = safe.get("extracted") or {}
        grn  = safe.get("grn_posting") or {}
        miro = safe.get("miro_posting") or {}
        park = safe.get("miro_parking") or {}
        fb60 = safe.get("fb60_posting") or {}
        items.append(DocumentListItem(
            id=safe.get("_id") or safe.get("id", ""),
            document_id=safe["document_id"],
            type=safe["type"],
            tcode=safe["tcode"],
            status=safe["status"],
            uploaded_at=safe["uploaded_at"],
            vendor_name=extracted.get("vendor_name") or "",
            amount=str(extracted.get("gross_amount") or ""),
            invoice_subtype=safe.get("invoice_subtype") or "",
            grn_number=grn.get("grn_number") or "",
            miro_number=miro.get("miro_number") or "",
            park_number=park.get("park_number") or "",
            fb60_number=fb60.get("fb60_number") or "",
        ))

    pages = math.ceil(total / limit) if total else 1
    return DocumentListResponse(documents=items, total=total, page=page, limit=limit, pages=pages)


# ---------------------------------------------------------------------------
# GET /api/documents/from-mail
#
# Everything that arrived by email, with what became of it: who sent it, what
# OCR read, where SAP routed it, and which document it ended up as. The web
# history answers "what did we process"; this answers "what did the mailbox
# bring us, and did it land" — the question people actually ask when a vendor
# says they emailed an invoice.
# ---------------------------------------------------------------------------

@router.get("/from-mail")
async def documents_from_mail(
    current_user: CurrentUser,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=25, ge=1, le=100),
    outcome: str | None = Query(default=None, description="posted | awaiting | held | failed"),
) -> dict[str, Any]:
    from sqlalchemy import func, select

    from src.models.document import DocumentRow

    stmt = select(DocumentRow).where(DocumentRow.source == "email")
    count_stmt = select(func.count()).select_from(DocumentRow).where(DocumentRow.source == "email")

    user_tenant = getattr(current_user, "tenant_id", None)
    if user_tenant:
        stmt = stmt.where(DocumentRow.tenant_id == user_tenant)
        count_stmt = count_stmt.where(DocumentRow.tenant_id == user_tenant)
    if current_user.role == "operator":
        # Operators see what they sent, matching the rule on the main list.
        stmt = stmt.where(DocumentRow.uploaded_by == current_user.sub)
        count_stmt = count_stmt.where(DocumentRow.uploaded_by == current_user.sub)

    stmt = stmt.order_by(DocumentRow.uploaded_at.desc()).offset((page - 1) * limit).limit(limit)

    async with AsyncSessionLocal() as session:
        rows = (await session.execute(stmt)).scalars().all()
        total = (await session.execute(count_stmt)).scalar() or 0

    items = [_mail_item(serialize_doc(r.to_dict())) for r in rows]
    if outcome:
        items = [i for i in items if i["outcome"] == outcome]

    return {
        "documents": items,
        "total": total,
        "page": page,
        "limit": limit,
        "pages": math.ceil(total / limit) if total else 1,
    }


def _mail_item(doc: dict[str, Any]) -> dict[str, Any]:
    """Flatten one document into the columns this view needs.

    Assembled server-side so the page renders a table rather than digging
    through four nested blobs to answer "did it post".
    """
    extracted = doc.get("extracted") or {}
    pipeline  = doc.get("pipeline") or {}
    routing   = pipeline.get("routing") or {}
    autopost  = pipeline.get("autopost") or {}
    meta      = doc.get("source_metadata") or {}
    miro      = doc.get("miro_posting") or {}
    grn       = doc.get("grn_posting") or {}
    fb60      = doc.get("fb60_posting") or {}

    # What was actually done, in the order a reader cares about: a posted
    # document is finished, a held one needs a person, everything else is still
    # moving or has failed.
    if miro.get("status") == "success" or fb60.get("status") == "success":
        outcome, action = "posted", "Posted to SAP"
    elif doc.get("status") == "failed":
        outcome, action = "failed", "Failed"
    elif routing.get("route") == "hold":
        outcome, action = "held", "Needs attention"
    elif autopost.get("decision") == "manual_approval_required":
        outcome, action = "awaiting", "Awaiting approval"
    else:
        outcome, action = "processing", "Processing"

    failed_gates = [g["gate"] for g in (autopost.get("gates") or []) if not g.get("passed")]

    return {
        "document_id":  doc.get("document_id"),
        "status":       doc.get("status"),
        "received_at":  doc.get("uploaded_at"),
        # From the mail itself
        "sender":       doc.get("uploaded_by"),
        "subject":      meta.get("subject", ""),
        "mailbox":      meta.get("mailbox", ""),
        "sender_trusted": meta.get("sender_trusted"),
        "attachment":   (doc.get("file") or {}).get("original_name", ""),
        # What OCR read
        "invoice_no":   extracted.get("invoice_no", ""),
        "vendor_name":  extracted.get("vendor_name", ""),
        "gross_amount": extracted.get("gross_amount", ""),
        "confidence":   extracted.get("confidence_score"),
        "line_items":   len(extracted.get("line_items") or []),
        # Where it went
        "po_number":    routing.get("po_number") or extracted.get("po_number", ""),
        "route":        routing.get("route", ""),
        "invoice_subtype": doc.get("invoice_subtype"),
        "tcode":        doc.get("tcode", ""),
        "reason":       routing.get("reason", ""),
        # What happened
        "outcome":      outcome,
        "action":       action,
        "decision":     autopost.get("decision", ""),
        "failed_gates": failed_gates,
        "grn_number":   grn.get("grn_number", ""),
        "miro_number":  miro.get("miro_number", "") or fb60.get("fb60_number", ""),
    }


# ---------------------------------------------------------------------------
# GET /api/documents/group/{group_id}
#
# A multi-invoice PDF, once split, produces several independent documents.
# This answers "which documents came from the same upload" — the UI uses it
# to show them as tabs instead of making the user find each one separately
# in the main list.
# ---------------------------------------------------------------------------

@router.get("/group/{group_id}")
async def get_document_group(group_id: str, current_user: CurrentUser) -> dict[str, Any]:
    from sqlalchemy import select

    from src.models.document import DocumentRow

    stmt = select(DocumentRow).where(
        DocumentRow.source_metadata["segmentation"]["group_id"].astext == group_id
    )
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(stmt)).scalars().all()

    docs = [serialize_doc(r.to_dict()) for r in rows]
    docs = [d for d in docs if _tenant_ok(d, current_user)]

    def _seg(d: dict[str, Any]) -> dict[str, Any]:
        return (d.get("source_metadata") or {}).get("segmentation") or {}

    docs.sort(key=lambda d: _seg(d).get("part") or 0)

    items = [{
        "document_id":     d["document_id"],
        "part":            _seg(d).get("part"),
        "of":              _seg(d).get("of"),
        "invoice_no":      (d.get("extracted") or {}).get("invoice_no") or _seg(d).get("invoice_no") or "",
        "vendor_name":     (d.get("extracted") or {}).get("vendor_name") or "",
        "status":          d.get("status"),
        "confidence":      _seg(d).get("confidence"),
        "forced_manual_review": _seg(d).get("forced_manual_review", False),
    } for d in docs]

    return {"group_id": group_id, "documents": items}


# ---------------------------------------------------------------------------
# GET /api/documents/{document_id}
# ---------------------------------------------------------------------------

@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(document_id: str, current_user: CurrentUser) -> DocumentResponse:
    async with AsyncSessionLocal() as session:
        doc = await DocumentRepository(session).find_by_document_id(document_id)

    if not doc:
        raise NotFoundError(f"Document '{document_id}' not found", error_code="DOCUMENT_NOT_FOUND")

    _assert_tenant(doc, current_user)
    safe = serialize_doc(doc)
    return DocumentResponse(
        id=safe.get("_id") or safe.get("id", ""),
        document_id=safe["document_id"],
        type=safe["type"],
        tcode=safe["tcode"],
        invoice_subtype=safe.get("invoice_subtype"),
        status=safe["status"],
        uploaded_by=safe["uploaded_by"],
        uploaded_at=safe["uploaded_at"],
        file=safe["file"],
        source_metadata=safe.get("source_metadata"),
        extracted=safe.get("extracted"),
        pipeline=safe.get("pipeline"),
        sap_validation=safe.get("sap_validation"),
        grn_posting=safe.get("grn_posting"),
        miro_posting=safe.get("miro_posting"),
        miro_parking=safe.get("miro_parking"),
        fb60_posting=safe.get("fb60_posting"),
        so_simulation=safe.get("so_simulation"),
        so_posting=safe.get("so_posting"),
        f26_simulation=safe.get("f26_simulation"),
        f26_posting=safe.get("f26_posting"),
        retry_count=safe.get("retry_count", 0),
        error_log=safe.get("error_log", []),
        created_at=safe["created_at"],
        updated_at=safe["updated_at"],
    )


# ---------------------------------------------------------------------------
# GET /api/documents/{document_id}/presigned-url
# ---------------------------------------------------------------------------

@router.get("/{document_id}/presigned-url", response_model=PresignedUrlResponse)
async def get_presigned_url_endpoint(document_id: str, current_user: CurrentUser) -> PresignedUrlResponse:
    async with AsyncSessionLocal() as session:
        doc = await DocumentRepository(session).find_by_document_id(document_id)

    if not doc:
        raise NotFoundError(f"Document '{document_id}' not found", error_code="DOCUMENT_NOT_FOUND")

    _assert_tenant(doc, current_user)
    s3_key: str = (doc.get("file") or {}).get("s3_key", "")
    if not s3_key:
        raise NotFoundError("File has not been uploaded yet", error_code="FILE_NOT_AVAILABLE")

    expiry = 3600
    url = await get_presigned_url(s3_key, expiry=expiry)
    return PresignedUrlResponse(url=url, expires_in=expiry)


# ---------------------------------------------------------------------------
# POST /api/documents/{document_id}/retry
# ---------------------------------------------------------------------------

@router.post("/{document_id}/retry", status_code=202)
async def retry_extraction(document_id: str, current_user: CurrentUser) -> dict:
    import asyncio as _asyncio
    from src.workers.ocr_worker import run_extraction_direct

    async with AsyncSessionLocal() as session:
        repo = DocumentRepository(session)
        doc = await repo.find_by_document_id(document_id)
        if not doc:
            raise NotFoundError(f"Document '{document_id}' not found", error_code="DOCUMENT_NOT_FOUND")
        _assert_tenant(doc, current_user)
        await repo.update_status(doc["id"], DocumentStatus.UPLOADED)
        await session.commit()

    _asyncio.create_task(run_extraction_direct(document_id), name=f"ocr-retry-{document_id}")
    return {"document_id": document_id, "status": "processing", "message": "OCR retry started."}


# ---------------------------------------------------------------------------
# POST /api/documents/{document_id}/validate
# ---------------------------------------------------------------------------

@router.post("/{document_id}/validate", response_model=ValidationTriggerResponse, status_code=202)
async def trigger_validation(document_id: str, current_user: CurrentUser) -> ValidationTriggerResponse:
    async with AsyncSessionLocal() as session:
        doc = await DocumentRepository(session).find_by_document_id(document_id)

    if not doc:
        raise NotFoundError(f"Document '{document_id}' not found", error_code="DOCUMENT_NOT_FOUND")
    _assert_tenant(doc, current_user)

    current_status = doc.get("status", "")
    if current_status not in {DocumentStatus.EXTRACTED, DocumentStatus.VALIDATED, DocumentStatus.FAILED}:
        raise ValidationError(
            f"Document must be in 'extracted' state to validate (current: {current_status})",
            error_code="INVALID_STATUS_TRANSITION",
        )

    try:
        await get_redis().xadd("document:validate", {
            "document_id":  document_id,
            "requested_by": current_user.sub,
            "timestamp":    datetime.now(UTC).isoformat(),
        })
    except Exception as exc:
        log.warning("Redis stream publish failed", error=str(exc))

    import asyncio as _asyncio
    from src.workers.sap_worker import run_validation_direct
    _asyncio.create_task(run_validation_direct(document_id), name=f"validate-{document_id}")

    return ValidationTriggerResponse(
        document_id=document_id, status="validating",
        message="SAP PO validation started in the background.",
    )


# ---------------------------------------------------------------------------
# GET /api/documents/{document_id}/validation
# ---------------------------------------------------------------------------

@router.get("/{document_id}/validation", response_model=ValidationResultResponse)
async def get_validation_result(document_id: str, current_user: CurrentUser) -> ValidationResultResponse:
    async with AsyncSessionLocal() as session:
        doc = await DocumentRepository(session).find_by_document_id(document_id)

    if not doc:
        raise NotFoundError(f"Document '{document_id}' not found", error_code="DOCUMENT_NOT_FOUND")
    _assert_tenant(doc, current_user)

    sap_validation = doc.get("sap_validation")
    if not sap_validation:
        raise NotFoundError(f"No validation result for document '{document_id}'", error_code="VALIDATION_NOT_FOUND")

    safe = serialize_doc(sap_validation)
    return ValidationResultResponse(
        document_id=document_id,
        overall_confidence=safe.get("overall_confidence", 0.0),
        header_confidence=safe.get("header_confidence", 0.0),
        line_item_confidence=safe.get("line_item_confidence", 0.0),
        gr_confidence=safe.get("gr_confidence", 0.0),
        mismatches=safe.get("mismatches", []),
        gr_status=safe.get("gr_status", []),
        is_valid=safe.get("is_valid", False),
        recommendation=safe.get("recommendation", ""),
    )


# ---------------------------------------------------------------------------
# GET /api/documents/{document_id}/miro-check
#
# Credit-note workflow, step 1: given the PO number extracted from the
# uploaded credit-note invoice, check whether a MIRO has already been posted
# against that PO. If so, SAP also returns the originally posted line items
# (quantity, price, tax, totals) so the caller can diff them against what was
# extracted from the credit-note invoice.
# ---------------------------------------------------------------------------

@router.get("/{document_id}/miro-check", response_model=MIRODetailResponse)
async def check_miro_status(document_id: str, current_user: CurrentUser) -> MIRODetailResponse:
    async with AsyncSessionLocal() as session:
        doc = await DocumentRepository(session).find_by_document_id(document_id)

    if not doc:
        raise NotFoundError(f"Document '{document_id}' not found", error_code="DOCUMENT_NOT_FOUND")
    _assert_tenant(doc, current_user)

    po_number = (doc.get("extracted") or {}).get("po_number") or ""
    if not po_number:
        raise ValidationError(
            "Document has no extracted PO number to check", error_code="PO_NUMBER_MISSING"
        )

    from src.services.sap_service import get_sap_service
    return await get_sap_service().fetch_miro_details(po_number)


# ---------------------------------------------------------------------------
# GET /api/documents/{document_id}/credit-compare
#
# Credit-note workflow, step 2: fetches the MIRO details for the extracted
# PO (same as miro-check) and diffs them line-by-line against the extracted
# credit-note invoice, returning per-line differences plus the system's
# Credit Memo / Subsequent Credit classification. Posting is a separate
# endpoint, added once the posting BAPI is confirmed.
# ---------------------------------------------------------------------------

@router.get("/{document_id}/credit-compare", response_model=CreditComparisonResponse)
async def compare_credit_note_document(
    document_id: str, current_user: CurrentUser
) -> CreditComparisonResponse:
    async with AsyncSessionLocal() as session:
        doc = await DocumentRepository(session).find_by_document_id(document_id)

    if not doc:
        raise NotFoundError(f"Document '{document_id}' not found", error_code="DOCUMENT_NOT_FOUND")
    _assert_tenant(doc, current_user)

    extracted = doc.get("extracted") or {}
    po_number = extracted.get("po_number") or ""
    if not po_number:
        raise ValidationError(
            "Document has no extracted PO number to check", error_code="PO_NUMBER_MISSING"
        )

    from src.services.credit_service import compare_credit_note
    from src.services.sap_service import get_sap_service

    miro = await get_sap_service().fetch_miro_details(po_number)
    return compare_credit_note(document_id, extracted, miro)


# ---------------------------------------------------------------------------
# POST /api/documents/{document_id}/post-miro
# ---------------------------------------------------------------------------

async def _assert_matches_sap(doc: dict[str, Any]) -> None:
    """Refuse to post a document whose figures disagree with the purchase order.

    The auto-post gates decide whether a posting may happen *unattended*. That
    left a hole: approving by hand skipped them entirely, so an invoice SAP had
    already contradicted could still be posted with one click. PO 4500022798 was
    the case that showed it — 1,000.00 billed as exempt against a PO of 1,000.00
    plus 18% tax, a 180.00 tax difference that nothing on the manual path looked at.

    Only the gates in BLOCKING_GATES are enforced here. A reviewer may still
    override a low-confidence extraction or a value above the unattended
    ceiling; those are judgements about reading the invoice. They may not
    override a disagreement with SAP's own record, because no amount of reading
    makes the two agree. Fix the invoice or the PO, then re-validate.
    """
    from src.services.autopost_service import blocking_failures

    failures = await blocking_failures(doc)
    if not failures:
        return

    reasons = " ".join(f["detail"] for f in failures if f.get("detail"))
    raise ValidationError(
        "This invoice does not match the purchase order in SAP, so it cannot be "
        f"posted. {reasons} Correct the invoice or the PO and re-validate.",
        error_code="SAP_DATA_MISMATCH",
    )


@router.post("/{document_id}/post-miro", response_model=MIROTriggerResponse, status_code=202)
async def post_to_miro(
    document_id: str,
    current_user: CurrentUser,
    _role: Annotated[Any, require_role("manager", "admin")] = None,
) -> MIROTriggerResponse:
    async with AsyncSessionLocal() as session:
        repo = DocumentRepository(session)
        doc = await repo.find_by_document_id(document_id)
        if not doc:
            raise NotFoundError(f"Document '{document_id}' not found", error_code="DOCUMENT_NOT_FOUND")
        _assert_tenant(doc, current_user)

        current_status = doc.get("status", "")
        if current_status == DocumentStatus.POSTING:
            raise ValidationError("MIRO posting is already in progress", error_code="ALREADY_POSTING")
        if current_status not in {DocumentStatus.VALIDATED, DocumentStatus.GR_POSTED}:
            raise ValidationError(
                f"Document must be VALIDATED or GR_POSTED (current: {current_status})",
                error_code="INVALID_STATUS_TRANSITION",
            )

        # Service PO: every validation gate (SES present, within PO line, within
        # what SAP still has available) must have passed before MIRO is allowed.
        if (doc.get("invoice_subtype") or "") == InvoiceSubtype.SERVICE_PO:
            gates = (doc.get("sap_validation") or {}).get("gates") or {}
            failed = [name for name, passed in gates.items() if not passed]
            if not gates or failed:
                raise ValidationError(
                    "Service PO validation has not passed"
                    + (f" (failed: {', '.join(failed)})" if failed else "")
                    + " — re-run validation before posting to MIRO.",
                    error_code="SERVICE_PO_VALIDATION_FAILED",
                )

        # Applies to every subtype, not just service POs.
        await _assert_matches_sap(doc)

        await repo.update_status(doc["id"], DocumentStatus.POSTING)
        await session.commit()

    try:
        await get_redis().xadd("document:post_miro", {
            "document_id":  document_id,
            "requested_by": current_user.sub,
            "timestamp":    datetime.now(UTC).isoformat(),
        })
    except Exception as exc:
        log.warning("Redis stream publish failed", error=str(exc))

    import asyncio as _asyncio
    from src.workers.sap_worker import run_miro_direct
    _asyncio.create_task(run_miro_direct(document_id, current_user.sub), name=f"miro-{document_id}")
    _asyncio.create_task(_write_doc_audit(
        action="document.sap.miro_posted",
        document_id=document_id,
        performed_by=current_user.sub,
    ))

    return MIROTriggerResponse(document_id=document_id, status="posting", message="MIRO posting started.")


# ---------------------------------------------------------------------------
# POST /api/documents/{document_id}/park-miro
#
# Material PO only — parks the MIRO invoice as a draft in SAP instead of
# posting it. Dead end from this app's perspective: any follow-up on the
# parked document (completing it into a real posted invoice) happens
# directly in SAP, not through this system.
# ---------------------------------------------------------------------------

@router.post("/{document_id}/park-miro", response_model=MIROParkTriggerResponse, status_code=202)
async def park_miro(
    document_id: str,
    current_user: CurrentUser,
    _role: Annotated[Any, require_role("manager", "admin")] = None,
) -> MIROParkTriggerResponse:
    async with AsyncSessionLocal() as session:
        repo = DocumentRepository(session)
        doc = await repo.find_by_document_id(document_id)
        if not doc:
            raise NotFoundError(f"Document '{document_id}' not found", error_code="DOCUMENT_NOT_FOUND")
        _assert_tenant(doc, current_user)

        invoice_subtype = doc.get("invoice_subtype") or ""
        if invoice_subtype in {InvoiceSubtype.SERVICE_PO, InvoiceSubtype.FREIGHT_PO}:
            raise ValidationError(
                "Park is only available for Material PO invoices", error_code="PARK_NOT_SUPPORTED"
            )

        current_status = doc.get("status", "")
        if current_status == DocumentStatus.POSTING:
            raise ValidationError("MIRO posting/parking is already in progress", error_code="ALREADY_POSTING")
        if current_status != DocumentStatus.VALIDATED:
            raise ValidationError(
                f"Document must be VALIDATED (current: {current_status})",
                error_code="INVALID_STATUS_TRANSITION",
            )
        # Parking still puts the document into SAP for someone to complete.
        await _assert_matches_sap(doc)

        await repo.update_status(doc["id"], DocumentStatus.POSTING)
        await session.commit()

    import asyncio as _asyncio
    from src.workers.sap_worker import run_miro_park_direct
    _asyncio.create_task(run_miro_park_direct(document_id, current_user.sub), name=f"miro-park-{document_id}")
    _asyncio.create_task(_write_doc_audit(
        action="document.sap.miro_parked",
        document_id=document_id,
        performed_by=current_user.sub,
    ))

    return MIROParkTriggerResponse(document_id=document_id, status="posting", message="MIRO parking started.")

    return MIROTriggerResponse(document_id=document_id, status="posting", message="MIRO posting started.")


# ---------------------------------------------------------------------------
# POST /api/documents/{document_id}/reroute
#
# Re-runs routing with a corrected PO number. Routing is read-only against SAP,
# so this is safe to repeat — unlike /process, which posts.
#
# Exists because the commonest hold is a PO number the document scan got wrong
# or that was mistyped on the invoice; without this the only remedy was to fix
# the PDF and upload it again.
# ---------------------------------------------------------------------------

@router.post("/{document_id}/reroute", status_code=200)
async def reroute_document(
    document_id: str,
    body: dict,
    current_user: CurrentUser,
) -> dict[str, Any]:
    po_number = str(body.get("po_number") or "").strip()
    if not po_number:
        raise ValidationError("A PO number is required.", error_code="MISSING_PO_NUMBER")

    async with AsyncSessionLocal() as session:
        repo = DocumentRepository(session)
        doc = await repo.find_by_document_id(document_id)
        if not doc:
            raise NotFoundError(f"Document '{document_id}' not found", error_code="DOCUMENT_NOT_FOUND")
        _assert_tenant(doc, current_user)

        if (doc.get("miro_posting") or {}).get("status") == "success":
            raise ValidationError(
                "This document has already been posted and cannot be re-routed.",
                error_code="ALREADY_POSTED",
            )

        from src.services.routing_service import classify
        routing = await classify([po_number])

        pipeline = dict(doc.get("pipeline") or {})
        pipeline["routing"] = routing
        pipeline["po_number_corrected_by"] = current_user.sub

        updates: dict[str, Any] = {"pipeline": pipeline}

        # Keep the extracted PO number in step with the correction, otherwise the
        # posting step would still use the number that failed.
        extracted = dict(doc.get("extracted") or {})
        if extracted:
            extracted["po_number"] = routing.get("po_number") or po_number
            updates["extracted"] = extracted

        if routing.get("invoice_subtype"):
            updates["invoice_subtype"] = routing["invoice_subtype"]
        if routing.get("tcode"):
            updates["tcode"] = routing["tcode"]

        # A corrected PO invalidates any validation done against the old one.
        updates["sap_validation"] = None

        await repo.update(doc["id"], updates)
        await session.commit()

    await _write_doc_audit(
        action="document.reroute",
        document_id=document_id,
        performed_by=current_user.sub,
        details={"po_number": po_number, "route": routing.get("route")},
    )

    return {
        "document_id": document_id,
        "po_number":   po_number,
        "route":       routing.get("route"),
        "resolved":    routing.get("resolved"),
        "reason":      routing.get("reason"),
    }


# ---------------------------------------------------------------------------
# POST /api/documents/{document_id}/process
#
# Executes whatever route SAP chose for this document, in one action:
#   miro_direct     -> validate, then post the invoice
#   migo_then_miro  -> post the goods receipt, then validate, then the invoice
#   fb60 / hold     -> refused, with the reason
#
# This is what removes "MIGO or MIRO?" as a decision the user has to make.
# ---------------------------------------------------------------------------

@router.post("/{document_id}/process", status_code=202)
async def process_document(
    document_id: str,
    current_user: CurrentUser,
    _role: Annotated[Any, require_role("manager", "admin")] = None,
) -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        doc = await DocumentRepository(session).find_by_document_id(document_id)
    if not doc:
        raise NotFoundError(f"Document '{document_id}' not found", error_code="DOCUMENT_NOT_FOUND")
    _assert_tenant(doc, current_user)

    current_status = doc.get("status", "")
    if current_status in {DocumentStatus.POSTING, DocumentStatus.GR_POSTING}:
        raise ValidationError("Processing is already in progress", error_code="ALREADY_POSTING")

    # This route ends in a MIRO posting, so it carries the same prohibition.
    await _assert_matches_sap(doc)

    routing = (doc.get("pipeline") or {}).get("routing") or {}
    route = routing.get("route") or ""

    # Refuse the non-executable routes here, synchronously, so the caller gets a
    # reason instead of a background task that quietly does nothing.
    from src.workers.process_worker import ProcessBlocked, run_process_direct
    from src.services.routing_service import Route
    if not route:
        raise ValidationError(
            "This document has not been routed yet.", error_code="NOT_ROUTED"
        )
    if route == Route.HOLD.value:
        raise ValidationError(
            routing.get("reason") or "This document needs attention before it can be posted.",
            error_code="ROUTE_HOLD",
        )
    if route == Route.FB60.value:
        raise ValidationError(
            "Non-PO invoice — complete the FB60 form to post it.",
            error_code="FB60_FORM_REQUIRED",
        )

    # The worker refuses an already-posted document too, but only into the log —
    # the caller would otherwise be told "processing" for work that will not run.
    miro = doc.get("miro_posting") or {}
    if miro.get("status") == "success" and miro.get("miro_number"):
        raise ValidationError(
            f"Already posted as MIRO {miro['miro_number']}.",
            error_code="ALREADY_POSTED",
        )

    import asyncio as _asyncio

    async def _run() -> None:
        try:
            await run_process_direct(document_id, current_user.sub)
        except ProcessBlocked as exc:
            log.warning("route execution blocked", document_id=document_id, reason=exc.reason)
        except Exception as exc:
            log.error("route execution failed", document_id=document_id, error=str(exc))

    _asyncio.create_task(_run(), name=f"process-{document_id}")
    _asyncio.create_task(_write_doc_audit(
        action="document.process",
        document_id=document_id,
        performed_by=current_user.sub,
        details={"route": route},
    ))

    return {
        "document_id": document_id,
        "route":       route,
        "status":      "processing",
        "message":     (
            "Posting goods receipt, then invoice." if route == Route.MIGO_THEN_MIRO.value
            else "Posting invoice."
        ),
    }


# ---------------------------------------------------------------------------
# POST /api/documents/{document_id}/post-grn
# ---------------------------------------------------------------------------

@router.post("/{document_id}/post-grn", response_model=GRNTriggerResponse, status_code=202)
async def post_to_grn(
    document_id: str,
    current_user: CurrentUser,
    _role: Annotated[Any, require_role("manager", "admin")] = None,
) -> GRNTriggerResponse:
    async with AsyncSessionLocal() as session:
        repo = DocumentRepository(session)
        doc = await repo.find_by_document_id(document_id)
        if not doc:
            raise NotFoundError(f"Document '{document_id}' not found", error_code="DOCUMENT_NOT_FOUND")
        _assert_tenant(doc, current_user)

        current_status = doc.get("status", "")
        if current_status == DocumentStatus.GR_POSTING:
            raise ValidationError("GR posting already in progress", error_code="ALREADY_POSTING")
        if current_status not in {DocumentStatus.EXTRACTED, DocumentStatus.VALIDATED, DocumentStatus.GR_POSTED}:
            raise ValidationError(
                f"Document must be EXTRACTED, VALIDATED or GR_POSTED (current: {current_status})",
                error_code="INVALID_STATUS_TRANSITION",
            )
        # A goods receipt against a PO the invoice disagrees with creates stock
        # movement that the invoice can never be matched to.
        await _assert_matches_sap(doc)

        await repo.update_status(doc["id"], DocumentStatus.GR_POSTING)
        await session.commit()

    import asyncio as _asyncio
    from src.workers.migo_worker import run_migo_direct
    _asyncio.create_task(run_migo_direct(document_id, current_user.sub), name=f"migo-{document_id}")
    _asyncio.create_task(_write_doc_audit(
        action="document.sap.grn_posted",
        document_id=document_id,
        performed_by=current_user.sub,
    ))

    return GRNTriggerResponse(document_id=document_id, status="gr_posting", message="GR posting started.")


# ---------------------------------------------------------------------------
# POST /api/documents/{document_id}/post-fb60
# ---------------------------------------------------------------------------

@router.post("/{document_id}/post-fb60", response_model=FB60TriggerResponse, status_code=202)
async def post_fb60(document_id: str, form_data: dict, current_user: CurrentUser) -> FB60TriggerResponse:
    async with AsyncSessionLocal() as session:
        doc = await DocumentRepository(session).find_by_document_id(document_id)

    if not doc:
        raise NotFoundError(f"Document {document_id} not found")
    _assert_tenant(doc, current_user)

    # A non-PO invoice has no purchase order to disagree with, so the PO gates
    # pass on their own. The one that still bites is not_duplicate — paying the
    # same non-PO invoice twice is the failure mode here.
    await _assert_matches_sap(doc)

    current_status = DocumentStatus(doc.get("status", ""))
    if current_status not in {DocumentStatus.EXTRACTED, DocumentStatus.FAILED}:
        raise ValidationError(
            f"Document must be EXTRACTED to post FB60 (current: {current_status})",
            error_code="INVALID_STATUS_TRANSITION",
        )

    import asyncio as _asyncio
    from src.workers.fb60_worker import run_fb60_direct
    _asyncio.create_task(run_fb60_direct(document_id, form_data, current_user.sub), name=f"fb60-{document_id}")

    return FB60TriggerResponse(document_id=document_id, status="posting", message="FB60 posting started.")


# ---------------------------------------------------------------------------
# POST /api/documents/{document_id}/so-simulate
# ---------------------------------------------------------------------------

@router.post("/{document_id}/so-simulate", status_code=202)
async def so_simulate(document_id: str, body: dict, current_user: CurrentUser):
    async with AsyncSessionLocal() as session:
        doc = await DocumentRepository(session).find_by_document_id(document_id)

    if not doc:
        raise NotFoundError(f"Document {document_id} not found")
    _assert_tenant(doc, current_user)

    customer_id = body.get("customer_id") or ""
    if not customer_id:
        raise ValidationError("customer_id is required", error_code="MISSING_CUSTOMER_ID")

    import asyncio as _asyncio
    from src.workers.so_worker import run_so_simulate
    _asyncio.create_task(run_so_simulate(document_id, customer_id), name=f"so-simulate-{document_id}")

    return {"document_id": document_id, "status": "simulating", "message": "Sales Order simulation started."}


# ---------------------------------------------------------------------------
# POST /api/documents/{document_id}/so-create
# ---------------------------------------------------------------------------

@router.post("/{document_id}/so-create", status_code=202)
async def so_create(document_id: str, body: dict, current_user: CurrentUser):
    async with AsyncSessionLocal() as session:
        doc = await DocumentRepository(session).find_by_document_id(document_id)

    if not doc:
        raise NotFoundError(f"Document {document_id} not found")
    _assert_tenant(doc, current_user)

    customer_id = body.get("customer_id") or ""
    if not customer_id:
        raise ValidationError("customer_id is required", error_code="MISSING_CUSTOMER_ID")

    import asyncio as _asyncio
    from src.workers.so_worker import run_so_create
    _asyncio.create_task(run_so_create(document_id, customer_id), name=f"so-create-{document_id}")

    return {"document_id": document_id, "status": "posting", "message": "Sales Order creation started."}


# ---------------------------------------------------------------------------
# POST /api/documents/{document_id}/f26-simulate
# ---------------------------------------------------------------------------

@router.post("/{document_id}/f26-simulate", response_model=F26SimulateTriggerResponse, status_code=202)
async def f26_simulate(
    document_id: str, form_data: dict, current_user: CurrentUser
) -> F26SimulateTriggerResponse:
    """Simulate F-26 customer payment (indicator='X'). Saves result; posting allowed after success."""
    async with AsyncSessionLocal() as session:
        doc = await DocumentRepository(session).find_by_document_id(document_id)

    if not doc:
        raise NotFoundError(f"Document {document_id} not found")
    _assert_tenant(doc, current_user)

    current_status = DocumentStatus(doc.get("status", ""))
    if current_status not in {DocumentStatus.EXTRACTED, DocumentStatus.SIMULATED, DocumentStatus.FAILED}:
        raise ValidationError(
            f"Document must be EXTRACTED to simulate F-26 (current: {current_status})",
            error_code="INVALID_STATUS_TRANSITION",
        )

    import asyncio as _asyncio
    from src.workers.f26_worker import run_f26_simulate
    _asyncio.create_task(
        run_f26_simulate(document_id, current_user.sub, form_data), name=f"f26-simulate-{document_id}"
    )

    return F26SimulateTriggerResponse(
        document_id=document_id, status="simulating", message="F-26 simulation started."
    )


# ---------------------------------------------------------------------------
# POST /api/documents/{document_id}/f26-post
# ---------------------------------------------------------------------------

@router.post("/{document_id}/f26-post", response_model=F26PostTriggerResponse, status_code=202)
async def f26_post(document_id: str, current_user: CurrentUser) -> F26PostTriggerResponse:
    """Post F-26 customer payment (indicator=''). Requires a successful simulation first."""
    async with AsyncSessionLocal() as session:
        doc = await DocumentRepository(session).find_by_document_id(document_id)

    if not doc:
        raise NotFoundError(f"Document {document_id} not found")
    _assert_tenant(doc, current_user)

    current_status = DocumentStatus(doc.get("status", ""))
    if current_status != DocumentStatus.SIMULATED:
        raise ValidationError(
            f"Document must be SIMULATED before posting F-26 (current: {current_status})",
            error_code="INVALID_STATUS_TRANSITION",
        )

    sim = doc.get("f26_simulation") or {}
    if not sim.get("success"):
        raise ValidationError(
            "Last F-26 simulation was not successful. Re-simulate before posting.",
            error_code="SIMULATION_NOT_SUCCESSFUL",
        )

    import asyncio as _asyncio
    from src.workers.f26_worker import run_f26_post

    async def _post_and_return():
        doc_num = await run_f26_post(document_id, current_user.sub)
        return doc_num

    _asyncio.create_task(_post_and_return(), name=f"f26-post-{document_id}")

    return F26PostTriggerResponse(
        document_id=document_id,
        status="posting",
        message="F-26 posting started. Poll document status for DOCUMENT_NUMBER.",
    )
