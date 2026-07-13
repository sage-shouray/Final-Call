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


class GRNItemData(BaseModel):
    po_item: str
    material: str
    quantity: str


class GRNPayload(BaseModel):
    po: str
    vendor: str
    reference_doc_no: str
    posting_date: str
    document_date: str
    po_items: list[GRNItemData]


class GRNResponse(BaseModel):
    grn_number: str = ""
    status: str = ""
    message: str = ""
    sap_response: dict[str, Any] = Field(default_factory=dict)
    success: bool = False
    already_done: bool = False

    @classmethod
    def parse_message(cls, raw: Any) -> str:
        if isinstance(raw, str):
            return raw
        if isinstance(raw, list):
            return " | ".join(str(item.get("MSG", item)) for item in raw if item)
        return str(raw) if raw else ""


# ---------------------------------------------------------------------------
# FB60 (Non-PO Invoice) payload shapes
# ---------------------------------------------------------------------------


class FB60InvoiceItem(BaseModel):
    Invoice_Line_item_no: int
    GL: str = ""
    Amount: float  # negative for vendor credit line
    Tax_Code: str = ""
    Business_Place: str = ""
    Value_Date: str = ""
    Assignment_No: str = ""
    Text: str = ""
    Cost_Center: str = ""
    Profit_Center: str = ""
    Special_Gl: str = ""
    Baseline_Date: str = ""
    WHT_Tax: str = ""


class FB60Data(BaseModel):
    CounterItem_No: int = 1
    Invoice_Doc_Date: str
    Document_type: str = "KR"
    Company_Code: str
    Posting_Date: str
    Currency: str = "INR"
    Reference: str = ""
    Header_Document_Text: str = ""
    Vendor: str
    Invoice_Items: list[FB60InvoiceItem]


class FB60Payload(BaseModel):
    data: list[FB60Data]


class FB60Response(BaseModel):
    fb60_number: str = ""
    status: str = ""
    message: str = ""
    sap_response: dict[str, Any] = Field(default_factory=dict)
    success: bool = False

    @classmethod
    def parse_message(cls, raw: Any) -> str:
        if isinstance(raw, str):
            return raw
        if isinstance(raw, list):
            return " | ".join(str(item.get("MSG", item.get("MESSAGE", item))) for item in raw if item)
        return str(raw) if raw else ""


# ---------------------------------------------------------------------------
# Service PO response — matches zspodetail/Detail response structure
# ---------------------------------------------------------------------------


class SAPServicePOGRNEntry(BaseModel):
    """SES/GRN entry within a service PO line item — populated when SES is approved."""
    SES_NUMBER: str = ""       # sheet_no in MIRO payload
    ENTRY_NO: str = ""         # reference_no in MIRO payload
    YEAR: str = ""             # reference_document_year
    ITEM: str = "0001"         # reference_doc_it


class SAPServicePOLineItem(BaseModel):
    ITEM_NUMBER: str = ""
    TYPE: str = ""             # ZSER for service items
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
    GRN: list[SAPServicePOGRNEntry] = Field(default_factory=list)


class SAPServicePOResponse(BaseModel):
    PO_NUMBER: str = ""
    PO_DATE: str = ""
    VENDOR_ID: str = ""
    VENDOR_NAME: str = ""
    CURRENCY: str = "INR"
    GROSS_AMOUNT: str = "0"
    NET_AMOUNT: str = "0"
    COM_CODE: str = ""
    BUYER_ID: str = ""
    PO_LINE_ITEMS: list[SAPServicePOLineItem] = Field(default_factory=list)
    raw_response: dict[str, Any] = Field(default_factory=dict)

    @property
    def ses_approved(self) -> bool:
        """True if at least one line item has an approved SES (GRN list non-empty)."""
        return any(item.GRN for item in self.PO_LINE_ITEMS)


# ---------------------------------------------------------------------------
# Service MIRO payload — uses zmiro_post/MIRO endpoint with sheet_no field
# ---------------------------------------------------------------------------


class ServiceMIROItemData(BaseModel):
    invoice_document_no: str
    po_number: str
    po_item: str
    reference_no: str           # SES entry number
    reference_document_year: str
    reference_doc_it: str
    tax_code: str
    item_amount: float
    quantity: float
    po_unit: str
    tax_amount: float           # included for service PO (unlike material MIRO)
    sheet_no: str               # SES sheet number — key difference from material MIRO


class ServiceMIROData(BaseModel):
    document_date: str
    posting_date: str
    reference_document_no: str
    company_code: str
    currency: str
    gross_amount: float
    payment_terms: str
    baseline_date: str
    item_data: list[ServiceMIROItemData]


class ServiceMIROPayload(BaseModel):
    data: list[ServiceMIROData]


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


# ---------------------------------------------------------------------------
# Sales Order (VA01) schemas
# ---------------------------------------------------------------------------

class SAPCustomer(BaseModel):
    CUSTOMER: str = ""
    CUSTOMER_NAME: str = ""
    CITY: str = ""
    POSTAL_CODE: str = ""
    REGION: str = ""
    STREET: str = ""
    TELEPHONE: str = ""
    ADDRESS_NUMBER: str = ""
    COUNTRY: str = ""
    CREATED_BY: str = ""
    CREATED_ON: int = 0
    COMPANY_CODE: str = ""
    SALES_ORGANIZATION: str = ""
    DISTRIBUTION_CHANNEL: str = ""
    DIVISION: str = ""
    EMAIL_ADDRESS: str = ""


class SOItemData(BaseModel):
    itm_number: str = ""
    material: str = ""
    plant: str = ""
    target_qty: float = 0
    target_qu: str = "ST"


class SOScheduleData(BaseModel):
    itm_number: str = ""
    req_date: str = ""
    req_qty: float = 0


class SOPartnerData(BaseModel):
    partn_role: str = ""
    partn_numb: str = ""


class SOPayload(BaseModel):
    doc_type: str = "TA"
    sales_org: str = ""
    distr_chan: str = ""
    division: str = ""
    purch_no_c: str = ""
    purch_date: str = ""
    items: list[SOItemData] = Field(default_factory=list)
    schedules: list[SOScheduleData] = Field(default_factory=list)
    partners: list[SOPartnerData] = Field(default_factory=list)


class SOSimulateResponse(BaseModel):
    success: bool = False
    message: str = ""
    sap_response: dict[str, Any] = Field(default_factory=dict)


class SOCreateResponse(BaseModel):
    sales_order_number: str = ""
    success: bool = False
    message: str = ""
    sap_response: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# F-26 (Customer Payment) schemas — ZINV_PAY/INV_PAYMENT
# ---------------------------------------------------------------------------


class F26Payload(BaseModel):
    """Payload for both simulation (indicator='X') and posting (indicator='')."""
    company_code:  str = ""
    customer:      str = ""
    invoice:       str = ""
    fiscal_year:   str = ""
    document_date: str = ""
    posting_date:  str = ""
    currency:      str = "INR"
    amount:        str = ""
    bank_gl:       str = ""
    value_date:    str = ""
    reference:     str = ""
    header_text:   str = ""
    item_text:     str = ""
    indicator:     str = "X"   # "X" = simulate, "" = post


class F26ReturnItem(BaseModel):
    TYPE:    str = ""
    ID:      str = ""
    NUMBER:  int = 0
    MESSAGE: str = ""


class F26Response(BaseModel):
    STATUS:          str = ""
    MESSAGE:         str = ""
    RETURN:          list[F26ReturnItem] = Field(default_factory=list)
    DOCUMENT_NUMBER: str = ""   # only present on actual posting
    success:         bool = False
    is_simulation:   bool = True
    sap_response:    dict[str, Any] = Field(default_factory=dict)
