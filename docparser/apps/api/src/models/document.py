"""Document domain models — maps to the 'documents' MongoDB collection."""
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import Field

from src.models.base import TimestampedModel, _utcnow


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class DocumentType(StrEnum):
    VENDOR_INVOICE = "vendor_invoice"
    BANK_STATEMENT = "bank_statement"
    PAYMENT_ADVICE = "payment_advice"
    GOODS_RECEIPT = "goods_receipt"
    FREIGHT_INVOICE = "freight_invoice"


class TCode(StrEnum):
    MIRO = "MIRO"
    FB60 = "FB60"
    FF67 = "FF67"
    F28 = "F-28"
    MIGO = "MIGO"


class DocumentStatus(StrEnum):
    UPLOADED = "uploaded"
    EXTRACTING = "extracting"
    EXTRACTED = "extracted"
    VALIDATING = "validating"
    VALIDATED = "validated"
    GR_POSTING = "gr_posting"
    GR_POSTED = "gr_posted"
    POSTING = "posting"
    POSTED = "posted"
    FAILED = "failed"


class InvoiceSubtype(StrEnum):
    PO = "po"
    NON_PO = "non_po"


class MIROStatus(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"


class FB60Status(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"


class GRNStatus(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"
    PENDING = "pending"


# Automatic tcode assignment per document type
TCODE_MAP: dict[DocumentType, TCode] = {
    DocumentType.VENDOR_INVOICE: TCode.MIRO,
    DocumentType.BANK_STATEMENT: TCode.FF67,
    DocumentType.PAYMENT_ADVICE: TCode.F28,
    DocumentType.GOODS_RECEIPT: TCode.MIGO,
    DocumentType.FREIGHT_INVOICE: TCode.MIRO,
}


# ---------------------------------------------------------------------------
# Embedded models
# ---------------------------------------------------------------------------


class FileMetadata(TimestampedModel.__bases__[0]):  # plain BaseModel, no _id
    """Metadata for the uploaded file stored in S3."""

    original_name: str
    s3_key: str = ""
    size_bytes: int = Field(ge=0)
    mime_type: str


class LineItem(TimestampedModel.__bases__[0]):
    """One line from an extracted invoice / GR."""

    line_number: str = ""           # 5-digit padded string from OCR e.g. "00010"
    material_code: str = ""
    description: str = ""
    quantity: Decimal = Decimal("0")
    uom: str = ""
    unit_rate: Decimal = Decimal("0")
    amount: Decimal = Decimal("0")
    tax_code: str = ""
    tax_amount: Decimal = Decimal("0")
    hsn_code: str = ""
    grn_reference: str = ""


class ExtractedData(TimestampedModel.__bases__[0]):
    """Structured data extracted by the OCR / AI layer."""

    # Header
    invoice_no: str = ""
    invoice_date: str = ""          # normalised DD-MM-YYYY
    po_number: str = ""
    vendor_id: str = ""
    vendor_name: str = ""
    vendor_gstin: str = ""
    vendor_address: str = ""

    # Party details
    bill_to_name: str = ""
    bill_to_address: str = ""
    ship_to_name: str = ""
    ship_to_address: str = ""

    # Financials
    currency: str = "INR"
    gross_amount: Decimal = Decimal("0")
    tax_amount: Decimal = Decimal("0")
    net_amount: Decimal = Decimal("0")

    # Terms
    payment_terms: str = ""
    bank_details: str = ""
    reference_doc: str = ""

    # AI metadata
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)
    line_items: list[LineItem] = Field(default_factory=list)
    raw_ocr_response: dict[str, Any] = Field(default_factory=dict)


class MismatchEntry(TimestampedModel.__bases__[0]):
    field: str
    extracted_value: str
    sap_value: str
    severity: str = "warning"


class GRStatusEntry(TimestampedModel.__bases__[0]):
    gr_number: str
    gr_date: str
    quantity: Decimal
    amount: Decimal
    status: str


class SAPValidation(TimestampedModel.__bases__[0]):
    fetched_at: datetime = Field(default_factory=_utcnow)
    po_data: dict[str, Any] = Field(default_factory=dict)
    header_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    line_item_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    overall_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    mismatches: list[MismatchEntry] = Field(default_factory=list)
    gr_status: list[GRStatusEntry] = Field(default_factory=list)


class GRNPosting(TimestampedModel.__bases__[0]):
    posted_at: datetime = Field(default_factory=_utcnow)
    payload_sent: dict[str, Any] = Field(default_factory=dict)
    grn_number: str = ""
    sap_response: dict[str, Any] = Field(default_factory=dict)
    status: GRNStatus = GRNStatus.PENDING


class MIROPosting(TimestampedModel.__bases__[0]):
    posted_at: datetime = Field(default_factory=_utcnow)
    payload_sent: dict[str, Any] = Field(default_factory=dict)
    miro_number: str = ""
    sap_response: dict[str, Any] = Field(default_factory=dict)
    status: MIROStatus = MIROStatus.FAILED


class FB60Posting(TimestampedModel.__bases__[0]):
    posted_at: datetime = Field(default_factory=_utcnow)
    payload_sent: dict[str, Any] = Field(default_factory=dict)
    fb60_number: str = ""
    sap_response: dict[str, Any] = Field(default_factory=dict)
    status: FB60Status = FB60Status.FAILED


class ErrorEntry(TimestampedModel.__bases__[0]):
    timestamp: datetime = Field(default_factory=_utcnow)
    stage: str
    message: str
    detail: str = ""


# ---------------------------------------------------------------------------
# Root document model
# ---------------------------------------------------------------------------


class Document(TimestampedModel):
    """MongoDB document for the 'documents' collection."""

    document_id: str = Field(..., description="Human-readable ID e.g. DOC-2026-441200")
    type: DocumentType
    tcode: TCode
    invoice_subtype: InvoiceSubtype | None = None  # "po" | "non_po" for vendor invoices
    status: DocumentStatus = DocumentStatus.UPLOADED
    uploaded_by: str
    uploaded_at: datetime = Field(default_factory=_utcnow)
    file: FileMetadata
    extracted: ExtractedData | None = None
    sap_validation: SAPValidation | None = None
    grn_posting: GRNPosting | None = None
    miro_posting: MIROPosting | None = None
    fb60_posting: FB60Posting | None = None
    retry_count: int = Field(default=0, ge=0)
    error_log: list[ErrorEntry] = Field(default_factory=list)
