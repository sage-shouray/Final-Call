"""Pydantic schemas for document upload and retrieval endpoints."""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class DocumentListItem(BaseModel):
    """Lightweight document summary for the dashboard list view."""

    id: str
    document_id: str
    type: str
    tcode: str
    status: str
    uploaded_at: str
    vendor_name: str = ""
    amount: str = ""
    invoice_subtype: str = ""
    grn_number: str = ""
    miro_number: str = ""
    fb60_number: str = ""


class DocumentListResponse(BaseModel):
    documents: list[DocumentListItem]
    total: int
    page: int
    limit: int
    pages: int


class DocumentUploadResponse(BaseModel):
    document_id: str
    status: str
    message: str


class PresignedUrlResponse(BaseModel):
    url: str
    expires_in: int  # seconds


class ValidationTriggerResponse(BaseModel):
    document_id: str
    status: str
    message: str


class ValidationResultResponse(BaseModel):
    document_id: str
    overall_confidence: float
    header_confidence: float
    line_item_confidence: float
    gr_confidence: float
    mismatches: list[dict[str, Any]]
    gr_status: list[dict[str, Any]]
    is_valid: bool
    recommendation: str


class MIROTriggerResponse(BaseModel):
    document_id: str
    status: str
    message: str


class GRNTriggerResponse(BaseModel):
    document_id: str
    status: str
    message: str


class FB60TriggerResponse(BaseModel):
    document_id: str
    status: str
    message: str


class F26SimulateTriggerResponse(BaseModel):
    document_id: str
    status: str
    message: str


class F26PostTriggerResponse(BaseModel):
    document_id: str
    status: str
    message: str
    document_number: str = ""


class DocumentResponse(BaseModel):
    """Serialised document returned to the frontend."""

    id: str
    document_id: str
    type: str
    tcode: str
    invoice_subtype: str | None = None
    status: str
    uploaded_by: str
    uploaded_at: str
    file: dict[str, Any]
    extracted: dict[str, Any] | None = None
    sap_validation: dict[str, Any] | None = None
    grn_posting: dict[str, Any] | None = None
    miro_posting: dict[str, Any] | None = None
    fb60_posting: dict[str, Any] | None = None
    f26_simulation: dict[str, Any] | None = None
    f26_posting: dict[str, Any] | None = None
    retry_count: int
    error_log: list[dict[str, Any]]
    created_at: str
    updated_at: str
