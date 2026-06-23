"""Document endpoints — upload, status polling, presigned URL, SAP integration.

POST /api/documents/upload                       — multipart upload, triggers async OCR
GET  /api/documents/{document_id}                — poll full document state
GET  /api/documents/{document_id}/presigned-url  — temporary view URL
POST /api/documents/{document_id}/validate       — trigger SAP PO validation
GET  /api/documents/{document_id}/validation     — get validation result
POST /api/documents/{document_id}/post-miro      — post to SAP MIRO (manager/admin only)
"""
import math
import random
from datetime import UTC, datetime
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Form, Query, UploadFile

from src.database import get_database
from src.exceptions import NotFoundError, ValidationError
from src.middleware.auth import CurrentUser, require_role
from src.models.document import TCODE_MAP, Document, DocumentStatus, DocumentType, FileMetadata, InvoiceSubtype
from src.repositories.document_repository import DocumentRepository
from src.schemas.documents import (
    DocumentListItem,
    DocumentListResponse,
    DocumentResponse,
    DocumentUploadResponse,
    FB60TriggerResponse,
    GRNTriggerResponse,
    MIROTriggerResponse,
    PresignedUrlResponse,
    ValidationResultResponse,
    ValidationTriggerResponse,
)
from src.services.storage_service import (
    build_s3_key,
    get_presigned_url,
    upload_file,
    validate_upload,
)
from src.utils.redis_client import get_redis
from src.utils.serializer import serialize_doc

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/documents", tags=["Documents"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _generate_document_id() -> str:
    year = datetime.now(UTC).year
    suffix = str(random.randint(100_000, 999_999))
    return f"DOC-{year}-{suffix}"


# ---------------------------------------------------------------------------
# POST /api/documents/upload
# ---------------------------------------------------------------------------


@router.post(
    "/upload",
    response_model=DocumentUploadResponse,
    status_code=202,
    summary="Upload a document and trigger async OCR extraction",
)
async def upload_document(
    current_user: CurrentUser,
    file: UploadFile,
    document_type: str = Form(...),
    invoice_subtype: str = Form(default=""),
) -> DocumentUploadResponse:
    # ── Validate document_type ──────────────────────────────────────────────
    try:
        doc_type = DocumentType(document_type)
    except ValueError:
        raise ValidationError(
            f"Invalid document_type '{document_type}'. "
            f"Allowed: {[t.value for t in DocumentType]}",
            error_code="INVALID_DOCUMENT_TYPE",
        )

    # ── Read file bytes ─────────────────────────────────────────────────────
    file_bytes = await file.read()
    content_type = file.content_type or "application/octet-stream"
    filename = file.filename or "upload"

    # ── File validation (type, size, magic bytes) ───────────────────────────
    validate_upload(file_bytes, filename, content_type)

    # ── Generate document ID ────────────────────────────────────────────────
    document_id = _generate_document_id()

    # ── a. Save initial record in MongoDB (status = uploaded) ───────────────
    db = get_database()
    doc_repo = DocumentRepository(db)

    # Pre-compute the S3 key so the record is consistent from the start
    s3_key = build_s3_key(doc_type.value, document_id, filename)

    parsed_subtype: InvoiceSubtype | None = None
    if invoice_subtype:
        try:
            parsed_subtype = InvoiceSubtype(invoice_subtype)
        except ValueError:
            pass

    from src.models.document import TCode as _TCode
    tcode = (
        _TCode.FB60
        if parsed_subtype == InvoiceSubtype.NON_PO
        else TCODE_MAP[doc_type]
    )

    doc = Document(
        document_id=document_id,
        type=doc_type,
        tcode=tcode,
        invoice_subtype=parsed_subtype,
        status=DocumentStatus.UPLOADED,
        uploaded_by=current_user.sub,
        file=FileMetadata(
            original_name=filename,
            s3_key=s3_key,
            size_bytes=len(file_bytes),
            mime_type=content_type,
        ),
    )
    mongo_id = await doc_repo.create(doc.to_mongo())
    log.info("document record created", document_id=document_id, mongo_id=mongo_id)

    # ── b. Upload to S3 ─────────────────────────────────────────────────────
    try:
        actual_key = await upload_file(
            file_bytes,
            filename,
            content_type,
            doc_type.value,
            document_id,
            uploaded_by=current_user.sub,
        )
    except Exception as exc:
        # S3 failure → mark document failed so it's visible in the UI
        await doc_repo.update_status(
            mongo_id,
            DocumentStatus.FAILED,
            error_entry={
                "stage": "upload",
                "message": f"S3 upload failed: {exc}",
                "detail": type(exc).__name__,
                "timestamp": datetime.now(UTC),
            },
        )
        raise

    # ── c. Update s3_key on the record (pre-built key matches, but confirm) ──
    if actual_key != s3_key:
        await doc_repo.update(mongo_id, {"file.s3_key": actual_key})

    # ── d. Publish upload event to Redis Stream ─────────────────────────────
    try:
        redis = get_redis()
        await redis.xadd(
            "document:uploaded",
            {
                "document_id": document_id,
                "mongo_id": mongo_id,
                "uploaded_by": current_user.sub,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )
    except Exception as exc:
        # Non-fatal — the task will still run
        log.warning("Redis stream publish failed", error=str(exc), document_id=document_id)

    # ── e. Run OCR extraction as a background asyncio task ──────────────────
    import asyncio as _asyncio

    from src.workers.ocr_worker import run_extraction_direct

    _asyncio.create_task(
        run_extraction_direct(document_id),
        name=f"ocr-{document_id}",
    )
    log.info("OCR task started", document_id=document_id)

    return DocumentUploadResponse(
        document_id=document_id,
        status="processing",
        message="Document uploaded successfully. Extraction started in the background.",
    )


# ---------------------------------------------------------------------------
# GET /api/documents  (list with filters + pagination)
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=DocumentListResponse,
    summary="List documents with optional filters and full-text search",
)
async def list_documents(
    current_user: CurrentUser,
    status: str | None = Query(default=None, description="Filter by document status"),
    type: str | None = Query(default=None, description="Filter by document type"),
    tcode: str | None = Query(default=None, description="Filter by SAP T-code"),
    page: int = Query(default=1, ge=1, description="Page number (1-based)"),
    limit: int = Query(default=20, ge=1, le=100, description="Items per page"),
    search: str | None = Query(default=None, description="Search document_id, vendor, invoice_no, PO"),
) -> DocumentListResponse:
    filter_query: dict[str, Any] = {}

    if status:
        filter_query["status"] = status
    if type:
        filter_query["type"] = type
    if tcode:
        filter_query["tcode"] = tcode

    # Operators can only see their own documents; managers/admins see all
    if current_user.role == "operator":
        filter_query["uploaded_by"] = current_user.sub

    if search:
        filter_query["$or"] = [
            {"document_id": {"$regex": search, "$options": "i"}},
            {"extracted.vendor_name": {"$regex": search, "$options": "i"}},
            {"extracted.invoice_no": {"$regex": search, "$options": "i"}},
            {"extracted.po_number": {"$regex": search, "$options": "i"}},
        ]

    skip = (page - 1) * limit
    db = get_database()
    docs, total = await DocumentRepository(db).list_documents(
        filter_query=filter_query,
        skip=skip,
        limit=limit,
    )

    items: list[DocumentListItem] = []
    for doc in docs:
        safe = serialize_doc(doc)
        extracted = safe.get("extracted") or {}
        grn = safe.get("grn_posting") or {}
        miro = safe.get("miro_posting") or {}
        fb60 = safe.get("fb60_posting") or {}
        items.append(
            DocumentListItem(
                id=safe["_id"],
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
                fb60_number=fb60.get("fb60_number") or "",
            )
        )

    pages = math.ceil(total / limit) if total else 1
    return DocumentListResponse(documents=items, total=total, page=page, limit=limit, pages=pages)


# ---------------------------------------------------------------------------
# GET /api/documents/{document_id}
# ---------------------------------------------------------------------------


@router.get(
    "/{document_id}",
    response_model=DocumentResponse,
    summary="Get full document state (used for polling)",
)
async def get_document(
    document_id: str,
    current_user: CurrentUser,
) -> DocumentResponse:
    db = get_database()
    doc = await DocumentRepository(db).find_by_document_id(document_id)
    if not doc:
        raise NotFoundError(
            f"Document '{document_id}' not found",
            error_code="DOCUMENT_NOT_FOUND",
        )

    safe = serialize_doc(doc)
    return DocumentResponse(
        id=safe["_id"],
        document_id=safe["document_id"],
        type=safe["type"],
        tcode=safe["tcode"],
        invoice_subtype=safe.get("invoice_subtype"),
        status=safe["status"],
        uploaded_by=safe["uploaded_by"],
        uploaded_at=safe["uploaded_at"],
        file=safe["file"],
        extracted=safe.get("extracted"),
        sap_validation=safe.get("sap_validation"),
        grn_posting=safe.get("grn_posting"),
        miro_posting=safe.get("miro_posting"),
        fb60_posting=safe.get("fb60_posting"),
        retry_count=safe.get("retry_count", 0),
        error_log=safe.get("error_log", []),
        created_at=safe["created_at"],
        updated_at=safe["updated_at"],
    )


# ---------------------------------------------------------------------------
# GET /api/documents/{document_id}/presigned-url
# ---------------------------------------------------------------------------


@router.get(
    "/{document_id}/presigned-url",
    response_model=PresignedUrlResponse,
    summary="Get a temporary S3 URL to view the uploaded file in the browser",
)
async def get_presigned_url_endpoint(
    document_id: str,
    current_user: CurrentUser,
) -> PresignedUrlResponse:
    db = get_database()
    doc = await DocumentRepository(db).find_by_document_id(document_id)
    if not doc:
        raise NotFoundError(
            f"Document '{document_id}' not found",
            error_code="DOCUMENT_NOT_FOUND",
        )

    s3_key: str = doc.get("file", {}).get("s3_key", "")
    if not s3_key:
        raise NotFoundError(
            "File has not been uploaded yet",
            error_code="FILE_NOT_AVAILABLE",
        )

    expiry = 3600  # 1 hour
    url = await get_presigned_url(s3_key, expiry=expiry)

    return PresignedUrlResponse(url=url, expires_in=expiry)


# ---------------------------------------------------------------------------
# POST /api/documents/{document_id}/retry
# ---------------------------------------------------------------------------


@router.post(
    "/{document_id}/retry",
    status_code=202,
    summary="Retry OCR extraction for a failed document",
)
async def retry_extraction(
    document_id: str,
    current_user: CurrentUser,
) -> dict:
    import asyncio as _asyncio
    from src.workers.ocr_worker import run_extraction_direct

    db = get_database()
    doc_repo = DocumentRepository(db)
    doc = await doc_repo.find_by_document_id(document_id)
    if not doc:
        raise NotFoundError(f"Document '{document_id}' not found", error_code="DOCUMENT_NOT_FOUND")

    mongo_id = str(doc["_id"])
    await doc_repo.update_status(mongo_id, DocumentStatus.UPLOADED)

    _asyncio.create_task(
        run_extraction_direct(document_id),
        name=f"ocr-retry-{document_id}",
    )
    log.info("OCR retry started", document_id=document_id)
    return {"document_id": document_id, "status": "processing", "message": "OCR retry started."}


# ---------------------------------------------------------------------------
# POST /api/documents/{document_id}/validate
# ---------------------------------------------------------------------------


@router.post(
    "/{document_id}/validate",
    response_model=ValidationTriggerResponse,
    status_code=202,
    summary="Trigger SAP PO validation for an extracted document",
)
async def trigger_validation(
    document_id: str,
    current_user: CurrentUser,
) -> ValidationTriggerResponse:
    db = get_database()
    doc = await DocumentRepository(db).find_by_document_id(document_id)
    if not doc:
        raise NotFoundError(f"Document '{document_id}' not found", error_code="DOCUMENT_NOT_FOUND")

    current_status = doc.get("status", "")
    if current_status not in {DocumentStatus.EXTRACTED, DocumentStatus.VALIDATED, DocumentStatus.FAILED}:
        raise ValidationError(
            f"Document must be in 'extracted' state to validate (current: {current_status})",
            error_code="INVALID_STATUS_TRANSITION",
        )

    # Publish trigger event to Redis Stream
    try:
        redis = get_redis()
        await redis.xadd(
            "document:validate",
            {
                "document_id": document_id,
                "requested_by": current_user.sub,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )
    except Exception as exc:
        log.warning("Redis stream publish failed", error=str(exc), document_id=document_id)

    import asyncio as _asyncio
    from src.workers.sap_worker import run_validation_direct
    _asyncio.create_task(
        run_validation_direct(document_id),
        name=f"validate-{document_id}",
    )
    log.info("SAP validation task started", document_id=document_id)

    return ValidationTriggerResponse(
        document_id=document_id,
        status="validating",
        message="SAP PO validation started in the background.",
    )


# ---------------------------------------------------------------------------
# GET /api/documents/{document_id}/validation
# ---------------------------------------------------------------------------


@router.get(
    "/{document_id}/validation",
    response_model=ValidationResultResponse,
    summary="Get the SAP validation result for a document",
)
async def get_validation_result(
    document_id: str,
    current_user: CurrentUser,
) -> ValidationResultResponse:
    db = get_database()
    doc = await DocumentRepository(db).find_by_document_id(document_id)
    if not doc:
        raise NotFoundError(f"Document '{document_id}' not found", error_code="DOCUMENT_NOT_FOUND")

    sap_validation = doc.get("sap_validation")
    if not sap_validation:
        raise NotFoundError(
            f"No validation result for document '{document_id}'",
            error_code="VALIDATION_NOT_FOUND",
        )

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
# POST /api/documents/{document_id}/post-miro
# ---------------------------------------------------------------------------


@router.post(
    "/{document_id}/post-miro",
    response_model=MIROTriggerResponse,
    status_code=202,
    summary="Post validated invoice to SAP MIRO (manager/admin only)",
)
async def post_to_miro(
    document_id: str,
    current_user: CurrentUser,
    _role: Annotated[Any, require_role("manager", "admin")] = None,
) -> MIROTriggerResponse:
    db = get_database()
    doc = await DocumentRepository(db).find_by_document_id(document_id)
    if not doc:
        raise NotFoundError(f"Document '{document_id}' not found", error_code="DOCUMENT_NOT_FOUND")

    current_status = doc.get("status", "")
    if current_status == DocumentStatus.POSTING:
        raise ValidationError(
            "MIRO posting is already in progress for this document",
            error_code="ALREADY_POSTING",
        )
    if current_status not in {DocumentStatus.VALIDATED, DocumentStatus.GR_POSTED}:
        raise ValidationError(
            f"Document must be in VALIDATED or GR_POSTED status before MIRO posting (current: {current_status})",
            error_code="INVALID_STATUS_TRANSITION",
        )

    # Atomically set status to POSTING so concurrent requests are blocked
    db2 = get_database()
    await DocumentRepository(db2).update_status(
        str(doc["_id"]), DocumentStatus.POSTING
    )

    # Publish trigger event to Redis Stream
    try:
        redis = get_redis()
        await redis.xadd(
            "document:post_miro",
            {
                "document_id": document_id,
                "requested_by": current_user.sub,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )
    except Exception as exc:
        log.warning("Redis stream publish failed", error=str(exc), document_id=document_id)

    import asyncio as _asyncio
    from src.workers.sap_worker import run_miro_direct
    _asyncio.create_task(
        run_miro_direct(document_id, current_user.sub),
        name=f"miro-{document_id}",
    )
    log.info("MIRO posting task started", document_id=document_id)

    return MIROTriggerResponse(
        document_id=document_id,
        status="posting",
        message="MIRO posting started in the background.",
    )


# ---------------------------------------------------------------------------
# POST /api/documents/{document_id}/post-grn
# ---------------------------------------------------------------------------


@router.post(
    "/{document_id}/post-grn",
    response_model=GRNTriggerResponse,
    status_code=202,
    summary="Post GR to SAP MIGO then MIRO (manager/admin only)",
)
async def post_to_grn(
    document_id: str,
    current_user: CurrentUser,
    _role: Annotated[Any, require_role("manager", "admin")] = None,
) -> GRNTriggerResponse:
    db = get_database()
    doc = await DocumentRepository(db).find_by_document_id(document_id)
    if not doc:
        raise NotFoundError(f"Document '{document_id}' not found", error_code="DOCUMENT_NOT_FOUND")

    current_status = doc.get("status", "")
    if current_status == DocumentStatus.GR_POSTING:
        raise ValidationError(
            "GR posting is already in progress for this document",
            error_code="ALREADY_POSTING",
        )
    if current_status not in {DocumentStatus.EXTRACTED, DocumentStatus.VALIDATED, DocumentStatus.GR_POSTED}:
        raise ValidationError(
            f"Document must be in EXTRACTED, VALIDATED or GR_POSTED status (current: {current_status})",
            error_code="INVALID_STATUS_TRANSITION",
        )

    # Atomically set status to GR_POSTING
    db2 = get_database()
    await DocumentRepository(db2).update_status(str(doc["_id"]), DocumentStatus.GR_POSTING)

    import asyncio as _asyncio
    from src.workers.migo_worker import run_migo_direct
    _asyncio.create_task(
        run_migo_direct(document_id, current_user.sub),
        name=f"migo-{document_id}",
    )
    log.info("MIGO task started", document_id=document_id)

    return GRNTriggerResponse(
        document_id=document_id,
        status="gr_posting",
        message="GR posting started. MIRO will follow automatically.",
    )


@router.post(
    "/{document_id}/post-fb60",
    response_model=FB60TriggerResponse,
    status_code=202,
    summary="Post Non-PO invoice to SAP FB60",
)
async def post_fb60(
    document_id: str,
    form_data: dict,
    current_user: CurrentUser,
) -> FB60TriggerResponse:
    db = get_database()
    doc = await DocumentRepository(db).find_by_document_id(document_id)
    if not doc:
        raise NotFoundError(f"Document {document_id} not found")

    current_status = DocumentStatus(doc.get("status", ""))
    if current_status not in {DocumentStatus.EXTRACTED, DocumentStatus.FAILED}:
        raise ValidationError(
            f"Document must be in EXTRACTED status to post FB60 (current: {current_status})",
            error_code="INVALID_STATUS_TRANSITION",
        )

    import asyncio as _asyncio
    from src.workers.fb60_worker import run_fb60_direct
    _asyncio.create_task(
        run_fb60_direct(document_id, form_data, current_user.sub),
        name=f"fb60-{document_id}",
    )
    log.info("FB60 task started", document_id=document_id)

    return FB60TriggerResponse(
        document_id=document_id,
        status="posting",
        message="FB60 posting started.",
    )
