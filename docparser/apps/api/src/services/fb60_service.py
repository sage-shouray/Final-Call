"""FB60 service — builds Non-PO invoice payload for SAP FB60 posting."""
from __future__ import annotations

from typing import Any

import structlog

from src.schemas.sap import FB60Data, FB60InvoiceItem, FB60Payload

log = structlog.get_logger(__name__)


def build_fb60_payload(form_data: dict[str, Any]) -> FB60Payload:
    """Build the FB60 POST payload from the frontend Non-PO invoice form.

    SAP zfb60/fb60post requires an explicit vendor credit line as the LAST
    item in Invoice_Items: GL="", Amount=-(sum of all GL lines). Without it
    SAP raises "FI/CO interface: Balance in transaction currency".
    """
    items: list[FB60InvoiceItem] = []
    total_amount: float = 0.0

    for idx, item in enumerate(form_data.get("invoice_items", []), start=1):
        amount = float(item.get("amount", 0))
        total_amount += amount
        items.append(FB60InvoiceItem(
            Invoice_Line_item_no=idx,
            GL=str(item.get("gl", "")).strip(),
            Amount=amount,
            Tax_Code=str(item.get("tax_code", "")).strip(),
            Business_Place=str(item.get("business_place", "")).strip(),
            Value_Date=str(item.get("value_date", "")).strip(),
            Assignment_No=str(item.get("assignment_no", "")).strip(),
            Text=str(item.get("text", "")).strip(),
            Cost_Center=str(item.get("cost_center", "")).strip(),
            Profit_Center=str(item.get("profit_center", "")).strip(),
            Special_Gl=str(item.get("special_gl", "")).strip(),
            Baseline_Date=str(item.get("baseline_date", "")).strip(),
            WHT_Tax=str(item.get("wht_tax", "")).strip(),
        ))

    # Vendor credit line — GL blank, amount = negative total
    vendor_line_no = len(items) + 1
    posting_date = str(form_data.get("posting_date", "")).strip()
    items.append(FB60InvoiceItem(
        Invoice_Line_item_no=vendor_line_no,
        GL="",
        Amount=-total_amount,
        Tax_Code="",
        Business_Place="",
        Value_Date=posting_date,
        Assignment_No="",
        Text=str(form_data.get("header_text", "")).strip(),
        Cost_Center="",
        Profit_Center="",
        Special_Gl="",
        Baseline_Date=posting_date,
        WHT_Tax="",
    ))

    data = FB60Data(
        CounterItem_No=1,
        Invoice_Doc_Date=str(form_data.get("invoice_doc_date", "")).strip(),
        Document_type=str(form_data.get("document_type", "KR")).strip(),
        Company_Code=str(form_data.get("company_code", "")).strip(),
        Posting_Date=posting_date,
        Currency=str(form_data.get("currency", "INR")).strip(),
        Reference=str(form_data.get("reference", "")).strip(),
        Header_Document_Text=str(form_data.get("header_text", "")).strip(),
        Vendor=str(form_data.get("vendor", "")).strip(),
        Invoice_Items=items,
    )

    log.info("FB60 payload built", vendor=data.Vendor, company_code=data.Company_Code,
             gl_lines=len(items) - 1, total_amount=total_amount)
    return FB60Payload(data=[data])
