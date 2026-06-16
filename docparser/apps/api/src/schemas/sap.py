"""Pydantic schemas for SAP API requests and responses."""
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# SAP PO/GRN response — matches actual zpo_grn/Detail response structure
# ---------------------------------------------------------------------------


class SAPGRNDetail(BaseModel):
    GR_NUMBER: str = ""
    GR_DATE: str = ""
    GR_ITEM_NUMBER: str = ""
    PO_ITEM_NUMBER: str = ""
    MATERIAL_CODE: str = ""
    DESCRIPTION: str = ""
    GR_QUANTITY: str = "0"
    UOM: str = ""
    UNIT_PRICE: str = "0"
    NET_AMOUNT: str = "0"
    STATUS: str = ""
    LOCATION: str = ""


class SAPPOLineItem(BaseModel):
    ITEM_NUMBER: str = ""
    MATERIAL_CODE: str = ""
    DESCRIPTION: str = ""
    ORDERED_QUANTITY: str = "0"
    RECEIVED_QUANTITY: str = "0"
    INVOICED_QUANTITY: str = "0"
    UOM: str = ""
    UNIT_PRICE: str = "0"
    NET_AMOUNT: str = "0"
    GROSS_AMOUNT: str = "0"
    TAX_CODE: str = ""
    TAX1_RATE: str = ""
    TAX1_AMOUNT: str = ""
    TAX2_RATE: str = ""
    TAX2_AMOUNT: str = ""
    STATUS: str = ""
    GRN: list[SAPGRNDetail] = Field(default_factory=list)


class SAPPOResponse(BaseModel):
    # Header fields from actual API response
    PO_NUMBER: str = ""
    PO_DATE: str = ""
    VENDOR_ID: str = ""
    VENDOR_NAME: str = ""
    VENDOR_GSTIN: str = ""
    VENDOR_STREET: str = ""
    VENDOR_CITY: str = ""
    VENDOR_STATE: str = ""
    SHIP_TO_NAME: str = ""
    SHIP_TO_STREET: str = ""
    SHIP_TO_CITY: str = ""
    SHIP_TO_STATE: str = ""
    SHIP_TO_GSTIN: str = ""
    COM_CODE: str = ""
    CURRENCY: str = "INR"
    GROSS_AMOUNT: str = "0"
    NET_AMOUNT: str = "0"
    BUYER_ID: str = ""
    PO_LINE_ITEMS: list[SAPPOLineItem] = Field(default_factory=list)
    raw_response: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# MIRO payload shapes
# ---------------------------------------------------------------------------


class MIROItemData(BaseModel):
    invoice_document_no: str
    po_number: str
    po_item: str
    reference_no: str
    reference_document_year: str
    reference_doc_it: str
    tax_code: str
    item_amount: float
    quantity: float
    po_unit: str
    tax_amount: int


class MIROData(BaseModel):
    document_date: str
    posting_date: str
    reference_document_no: str
    company_code: str
    currency: str
    gross_amount: float
    calc_tax_ind: str
    payment_terms: str
    baseline_date: str
    business_place: str
    item_data: list[MIROItemData]


class MIROPayload(BaseModel):
    data: list[MIROData]


class MIROResponse(BaseModel):
    miro_number: str = ""
    status: str = ""
    message: str = ""
    sap_response: dict[str, Any] = Field(default_factory=dict)
    success: bool = False

    @classmethod
    def parse_message(cls, raw: Any) -> str:
        """SAP MESSAGE can be a string or a list of dicts like [{'MSG': '...'}]."""
        if isinstance(raw, str):
            return raw
        if isinstance(raw, list):
            return " | ".join(str(item.get("MSG", item)) for item in raw if item)
        return str(raw) if raw else ""
