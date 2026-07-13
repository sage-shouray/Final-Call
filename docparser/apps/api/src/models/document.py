"""Document domain models — ORM table + Pydantic embedded schemas."""
import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import Field
from sqlalchemy import DateTime, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, PydanticBase, TimestampMixin, _utcnow


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class DocumentType(StrEnum):
    VENDOR_INVOICE  = "vendor_invoice"
    SALES_ORDER     = "sales_order"
    PAYMENT_ADVICE  = "payment_advice"
    GOODS_RECEIPT   = "goods_receipt"
    FREIGHT_INVOICE = "freight_invoice"


class TCode(StrEnum):
    MIRO = "MIRO"
    FB60 = "FB60"
    VA01 = "VA01"
    F28  = "F-28"
    MIGO = "MIGO"


class DocumentStatus(StrEnum):
    UPLOADED    = "uploaded"
    EXTRACTING  = "extracting"
    EXTRACTED   = "extracted"
    VALIDATING  = "validating"
    VALIDATED   = "validated"
    GR_POSTING  = "gr_posting"
    GR_POSTED   = "gr_posted"
    SIMULATING  = "simulating"
    SIMULATED   = "simulated"
    POSTING     = "posting"
    POSTED      = "posted"
    FAILED      = "failed"


class InvoiceSubtype(StrEnum):
    PO         = "po"
    SERVICE_PO = "service_po"
    FREIGHT_PO = "freight_po"
    NON_PO     = "non_po"


class MIROStatus(StrEnum):
    SUCCESS = "success"
    FAILED  = "failed"


class FB60Status(StrEnum):
    SUCCESS = "success"
    FAILED  = "failed"


class GRNStatus(StrEnum):
    SUCCESS = "success"
    FAILED  = "failed"
    PENDING = "pending"


TCODE_MAP: dict[DocumentType, TCode] = {
    DocumentType.VENDOR_INVOICE:  TCode.MIRO,
    DocumentType.SALES_ORDER:     TCode.VA01,
    DocumentType.PAYMENT_ADVICE:  TCode.F28,
    DocumentType.GOODS_RECEIPT:   TCode.MIGO,
    DocumentType.FREIGHT_INVOICE: TCode.MIRO,
}


# ---------------------------------------------------------------------------
# Pydantic embedded schemas (used for API responses / validation)
# These are stored as JSONB blobs inside the documents table.
# ---------------------------------------------------------------------------


class FileMetadata(PydanticBase):
    original_name: str
    s3_key: str = ""
    size_bytes: int = Field(ge=0)
    mime_type: str


class LineItem(PydanticBase):
    line_number:    str     = ""
    material_code:  str     = ""
    hsn_code:       str     = ""
    description:    str     = ""
    quantity:       Decimal = Decimal("0")
    uom:            str     = ""
    unit_rate:      Decimal = Decimal("0")
    discount:       Decimal = Decimal("0")
    taxable_amount: Decimal = Decimal("0")
    cgst_rate:      Decimal = Decimal("0")
    cgst_amount:    Decimal = Decimal("0")
    sgst_rate:      Decimal = Decimal("0")
    sgst_amount:    Decimal = Decimal("0")
    igst_rate:      Decimal = Decimal("0")
    igst_amount:    Decimal = Decimal("0")
    cess_rate:      Decimal = Decimal("0")
    cess_amount:    Decimal = Decimal("0")
    tax_code:       str     = ""
    tax_amount:     Decimal = Decimal("0")
    amount:         Decimal = Decimal("0")
    grn_reference:  str     = ""


class ExtractedData(PydanticBase):
    # Invoice header
    invoice_no:               str = ""
    invoice_date:             str = ""
    due_date:                 str = ""
    po_number:                str = ""
    delivery_note:            str = ""
    dispatch_doc_no:          str = ""
    dispatched_through:       str = ""
    destination:              str = ""
    invoice_type:             str = ""
    reverse_charge_applicable: str = ""
    place_of_supply:          str = ""

    # e-Invoice / e-Way Bill
    irn_number:           str = ""
    eway_bill_no:         str = ""
    eway_bill_date:       str = ""
    eway_bill_valid_upto: str = ""

    # Vendor
    vendor_id:         str = ""
    vendor_name:       str = ""
    vendor_gstin:      str = ""
    vendor_pan:        str = ""
    vendor_address:    str = ""
    vendor_state:      str = ""
    vendor_state_code: str = ""
    vendor_email:      str = ""
    vendor_phone:      str = ""

    # Buyer / Bill-to
    bill_to_name:       str = ""
    bill_to_gstin:      str = ""
    bill_to_address:    str = ""
    bill_to_state:      str = ""
    bill_to_state_code: str = ""

    # Ship-to
    ship_to_name:       str = ""
    ship_to_gstin:      str = ""
    ship_to_address:    str = ""
    ship_to_state:      str = ""
    ship_to_state_code: str = ""

    # Financials
    currency:           str     = "INR"
    taxable_amount:     Decimal = Decimal("0")
    cgst_rate:          Decimal = Decimal("0")
    cgst_amount:        Decimal = Decimal("0")
    sgst_rate:          Decimal = Decimal("0")
    sgst_amount:        Decimal = Decimal("0")
    igst_rate:          Decimal = Decimal("0")
    igst_amount:        Decimal = Decimal("0")
    cess_amount:        Decimal = Decimal("0")
    tds_amount:         Decimal = Decimal("0")
    tcs_amount:         Decimal = Decimal("0")
    discount_amount:    Decimal = Decimal("0")
    freight_charges:    Decimal = Decimal("0")
    packing_charges:    Decimal = Decimal("0")
    insurance_charges:  Decimal = Decimal("0")
    other_charges:      Decimal = Decimal("0")
    round_off:          Decimal = Decimal("0")
    tax_amount:         Decimal = Decimal("0")
    gross_amount:       Decimal = Decimal("0")
    net_amount:         Decimal = Decimal("0")

    # Payment & Bank
    payment_terms:   str = ""
    bank_name:       str = ""
    bank_account_no: str = ""
    bank_ifsc:       str = ""
    bank_branch:     str = ""
    bank_details:    str = ""

    # Transport / Logistics
    vehicle_no:        str = ""
    lr_no:             str = ""
    lr_date:           str = ""
    transport_name:    str = ""
    mode_of_transport: str = ""
    terms_of_delivery: str = ""

    # Other
    declaration:   str = ""
    notes:         str = ""
    reference_doc: str = ""

    # AI metadata
    confidence_score:   float          = Field(default=0.0, ge=0.0, le=1.0)
    line_items:         list[LineItem] = Field(default_factory=list)
    raw_ocr_response:   dict[str, Any] = Field(default_factory=dict)


class MismatchEntry(PydanticBase):
    field:           str
    extracted_value: str
    sap_value:       str
    severity:        str = "warning"


class GRStatusEntry(PydanticBase):
    gr_number: str
    gr_date:   str
    quantity:  Decimal
    amount:    Decimal
    status:    str


class SAPValidation(PydanticBase):
    fetched_at:          datetime        = Field(default_factory=_utcnow)
    po_data:             dict[str, Any]  = Field(default_factory=dict)
    header_confidence:   float           = Field(default=0.0, ge=0.0, le=1.0)
    line_item_confidence: float          = Field(default=0.0, ge=0.0, le=1.0)
    overall_confidence:  float           = Field(default=0.0, ge=0.0, le=1.0)
    mismatches:          list[MismatchEntry] = Field(default_factory=list)
    gr_status:           list[GRStatusEntry] = Field(default_factory=list)


class GRNPosting(PydanticBase):
    posted_at:    datetime       = Field(default_factory=_utcnow)
    payload_sent: dict[str, Any] = Field(default_factory=dict)
    grn_number:   str            = ""
    sap_response: dict[str, Any] = Field(default_factory=dict)
    status:       GRNStatus      = GRNStatus.PENDING


class MIROPosting(PydanticBase):
    posted_at:    datetime       = Field(default_factory=_utcnow)
    payload_sent: dict[str, Any] = Field(default_factory=dict)
    miro_number:  str            = ""
    sap_response: dict[str, Any] = Field(default_factory=dict)
    status:       MIROStatus     = MIROStatus.FAILED


class SOSimulation(PydanticBase):
    simulated_at: datetime       = Field(default_factory=_utcnow)
    payload_sent: dict[str, Any] = Field(default_factory=dict)
    sap_response: dict[str, Any] = Field(default_factory=dict)
    status:       str            = "pending"


class SOPosting(PydanticBase):
    posted_at:          datetime       = Field(default_factory=_utcnow)
    payload_sent:       dict[str, Any] = Field(default_factory=dict)
    sales_order_number: str            = ""
    sap_response:       dict[str, Any] = Field(default_factory=dict)
    status:             str            = "failed"


class FB60Posting(PydanticBase):
    posted_at:    datetime       = Field(default_factory=_utcnow)
    payload_sent: dict[str, Any] = Field(default_factory=dict)
    fb60_number:  str            = ""
    sap_response: dict[str, Any] = Field(default_factory=dict)
    status:       FB60Status     = FB60Status.FAILED


class ErrorEntry(PydanticBase):
    timestamp: datetime = Field(default_factory=_utcnow)
    stage:     str
    message:   str
    detail:    str = ""


# ---------------------------------------------------------------------------
# SQLAlchemy ORM table
# ---------------------------------------------------------------------------


class DocumentRow(Base, TimestampMixin):
    """PostgreSQL documents table.

    Nested structures (extracted data, SAP validation, postings, error log)
    are stored as JSONB columns so the existing dict-based service layer
    continues to work without deep refactoring.
    """

    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    document_id:      Mapped[str]       = mapped_column(String, unique=True, nullable=False)
    type:             Mapped[str]       = mapped_column(String, nullable=False)
    tcode:            Mapped[str]       = mapped_column(String, nullable=False)
    invoice_subtype:  Mapped[str | None] = mapped_column(String, nullable=True)
    status:           Mapped[str]       = mapped_column(String, nullable=False, default="uploaded")
    uploaded_by:      Mapped[str]       = mapped_column(String, nullable=False)
    uploaded_at:      Mapped[datetime]  = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )
    file:             Mapped[dict]      = mapped_column(JSONB, nullable=False, default=dict)
    extracted:        Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    sap_validation:   Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    grn_posting:      Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    miro_posting:     Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    fb60_posting:     Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    so_simulation:    Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    so_posting:       Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    f26_simulation:   Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    f26_posting:      Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    retry_count:      Mapped[int]       = mapped_column(Integer, nullable=False, default=0)
    error_log:        Mapped[list]      = mapped_column(JSONB, nullable=False, default=list)

    __table_args__ = (
        Index("ix_documents_document_id", "document_id"),
        Index("ix_documents_status", "status"),
        Index("ix_documents_type", "type"),
        Index("ix_documents_tcode", "tcode"),
        Index("ix_documents_uploaded_at", "uploaded_at"),
        Index("ix_documents_uploaded_by", "uploaded_by"),
        Index("ix_documents_status_uploaded_at", "status", "uploaded_at"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id":              self.id,
            "document_id":     self.document_id,
            "type":            self.type,
            "tcode":           self.tcode,
            "invoice_subtype": self.invoice_subtype,
            "status":          self.status,
            "uploaded_by":     self.uploaded_by,
            "uploaded_at":     self.uploaded_at,
            "file":            self.file or {},
            "extracted":       self.extracted,
            "sap_validation":  self.sap_validation,
            "grn_posting":     self.grn_posting,
            "miro_posting":    self.miro_posting,
            "fb60_posting":    self.fb60_posting,
            "so_simulation":   self.so_simulation,
            "so_posting":      self.so_posting,
            "f26_simulation":  self.f26_simulation,
            "f26_posting":     self.f26_posting,
            "retry_count":     self.retry_count,
            "error_log":       self.error_log or [],
            "created_at":      self.created_at,
            "updated_at":      self.updated_at,
        }
