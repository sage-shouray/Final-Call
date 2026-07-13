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
    DocumentListItem,
    DocumentListResponse,
    DocumentResponse,
    DocumentUploadResponse,
    F26PostTriggerResponse,
    F26SimulateTriggerResponse,
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
    try:
        doc_type = DocumentType(document_type)
    except ValueError:
        raise ValidationError(
            f"Invalid document_type '{document_type}'. Allowed: {[t.value for t in DocumentType]}",
            error_code="INVALID_DOCUMENT_TYPE",
        )

    file_bytes = await file.read()
    content_type = file.content_type or "application/octet-stream"
    filename = file.filename or "upload"
    validate_upload(file_bytes, filename, content_type)

    document_id = _generate_document_id()
    s3_key = build_s3_key(doc_type.value, document_id, filename)

    parsed_subtype: InvoiceSubtype | None = None
    if invoice_subtype:
        try:
            parsed_subtype = InvoiceSubtype(invoice_subtype)
        except ValueError:
            pass

    from src.models.document import TCode as _TCode
    tcode = _TCode.FB60 if parsed_subtype == InvoiceSubtype.NON_PO else TCODE_MAP[doc_type]

    doc_data: dict[str, Any] = {
        "document_id":     document_id,
        "type":            doc_type.value,
        "tcode":           tcode.value,
        "invoice_subtype": parsed_subtype.value if parsed_subtype else None,
        "status":          DocumentStatus.UPLOADED.value,
        "uploaded_by":     current_user.sub,
        "uploaded_at":     datetime.now(UTC),
        "file": {
            "original_name": filename,
            "s3_key":        s3_key,
            "size_bytes":    len(file_bytes),
            "mime_type":     content_type,
        },
        "error_log": [],
    }

    async with AsyncSessionLocal() as session:
        doc_repo = DocumentRepository(session)
        row_id = await doc_repo.create(doc_data)
        await session.commit()

    log.info("document record created", document_id=document_id, row_id=row_id)

    try:
        actual_key = await upload_file(
            file_bytes, filename, content_type, doc_type.value, document_id,
            uploaded_by=current_user.sub,
        )
    except Exception as exc:
        async with AsyncSessionLocal() as session:
            await DocumentRepository(session).update_status(
                row_id, DocumentStatus.FAILED,
                error_entry={"stage": "upload", "message": f"S3 upload failed: {exc}",
                             "detail": type(exc).__name__, "timestamp": datetime.now(UTC).isoformat()},
            )
            await session.commit()
        raise

    # Update s3_key if it changed
    if actual_key != s3_key:
        async with AsyncSessionLocal() as session:
            doc = await DocumentRepository(session).find_by_id(row_id)
            if doc:
                file_data = dict(doc.get("file") or {})
                file_data["s3_key"] = actual_key
                await DocumentRepository(session).update(row_id, {"file": file_data})
                await session.commit()

    try:
        redis = get_redis()
        await redis.xadd("document:uploaded", {
            "document_id": document_id,
            "row_id":      row_id,
            "uploaded_by": current_user.sub,
            "timestamp":   datetime.now(UTC).isoformat(),
        })
    except Exception as exc:
        log.warning("Redis stream publish failed", error=str(exc), document_id=document_id)

    import asyncio as _asyncio
    from src.workers.ocr_worker import run_extraction_direct

    async def _ocr_with_logging() -> None:
        try:
            await run_extraction_direct(document_id)
        except Exception as exc:
            log.error("OCR background task crashed", document_id=document_id, error=str(exc), exc_info=True)

    _asyncio.create_task(_ocr_with_logging(), name=f"ocr-{document_id}")
    log.info("OCR task started", document_id=document_id)

    return DocumentUploadResponse(
        document_id=document_id,
        status="processing",
        message="Document uploaded successfully. Extraction started in the background.",
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
            fb60_number=fb60.get("fb60_number") or "",
        ))

    pages = math.ceil(total / limit) if total else 1
    return DocumentListResponse(documents=items, total=total, page=page, limit=limit, pages=pages)


# ---------------------------------------------------------------------------
# GET /api/documents/{document_id}
# ---------------------------------------------------------------------------

@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(document_id: str, current_user: CurrentUser) -> DocumentResponse:
    async with AsyncSessionLocal() as session:
        doc = await DocumentRepository(session).find_by_document_id(document_id)

    if not doc:
        raise NotFoundError(f"Document '{document_id}' not found", error_code="DOCUMENT_NOT_FOUND")

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

@router.get("/{document_id}/presigned-url", response_model=PresignedUrlResponse)
async def get_presigned_url_endpoint(document_id: str, current_user: CurrentUser) -> PresignedUrlResponse:
    async with AsyncSessionLocal() as session:
        doc = await DocumentRepository(session).find_by_document_id(document_id)

    if not doc:
        raise NotFoundError(f"Document '{document_id}' not found", error_code="DOCUMENT_NOT_FOUND")

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
# POST /api/documents/{document_id}/post-miro
# ---------------------------------------------------------------------------

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

        current_status = doc.get("status", "")
        if current_status == DocumentStatus.POSTING:
            raise ValidationError("MIRO posting is already in progress", error_code="ALREADY_POSTING")
        if current_status not in {DocumentStatus.VALIDATED, DocumentStatus.GR_POSTED}:
            raise ValidationError(
                f"Document must be VALIDATED or GR_POSTED (current: {current_status})",
                error_code="INVALID_STATUS_TRANSITION",
            )
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

    return MIROTriggerResponse(document_id=document_id, status="posting", message="MIRO posting started.")


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

        current_status = doc.get("status", "")
        if current_status == DocumentStatus.GR_POSTING:
            raise ValidationError("GR posting already in progress", error_code="ALREADY_POSTING")
        if current_status not in {DocumentStatus.EXTRACTED, DocumentStatus.VALIDATED, DocumentStatus.GR_POSTED}:
            raise ValidationError(
                f"Document must be EXTRACTED, VALIDATED or GR_POSTED (current: {current_status})",
                error_code="INVALID_STATUS_TRANSITION",
            )
        await repo.update_status(doc["id"], DocumentStatus.GR_POSTING)
        await session.commit()

    import asyncio as _asyncio
    from src.workers.migo_worker import run_migo_direct
    _asyncio.create_task(run_migo_direct(document_id, current_user.sub), name=f"migo-{document_id}")

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
async def f26_simulate(document_id: str, current_user: CurrentUser) -> F26SimulateTriggerResponse:
    """Simulate F-26 customer payment (indicator='X'). Saves result; posting allowed after success."""
    async with AsyncSessionLocal() as session:
        doc = await DocumentRepository(session).find_by_document_id(document_id)

    if not doc:
        raise NotFoundError(f"Document {document_id} not found")

    current_status = DocumentStatus(doc.get("status", ""))
    if current_status not in {DocumentStatus.EXTRACTED, DocumentStatus.SIMULATED, DocumentStatus.FAILED}:
        raise ValidationError(
            f"Document must be EXTRACTED to simulate F-26 (current: {current_status})",
            error_code="INVALID_STATUS_TRANSITION",
        )

    import asyncio as _asyncio
    from src.workers.f26_worker import run_f26_simulate
    _asyncio.create_task(run_f26_simulate(document_id, current_user.sub), name=f"f26-simulate-{document_id}")

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
