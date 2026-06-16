"""MIRO payload builder — transforms extracted invoice + SAP PO/GRN data into ZMIRO payload."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog

from src.schemas.sap import MIROData, MIROItemData, MIROPayload, SAPPOResponse

log = structlog.get_logger(__name__)

_DEFAULT_PAYMENT_TERMS = "0001"
_CALC_TAX_IND = "X"


def _today_ddmmyyyy() -> str:
    return datetime.now(UTC).strftime("%d-%m-%Y")


def _safe_float(value: Any) -> float:
    try:
        return float(str(value).strip().replace(",", ""))
    except (ValueError, TypeError):
        return 0.0


def _gr_year(gr_date: str) -> str:
    """Extract year from GR_DATE field (format: YYYYMMDD → 'YYYY')."""
    if gr_date and len(gr_date) >= 4:
        return gr_date[:4]
    return str(datetime.now(UTC).year)


def build_miro_payload(
    extracted: dict[str, Any],
    sap_po: SAPPOResponse,
    validation: dict[str, Any],
) -> MIROPayload:
    """Build the MIRO POST payload.

    Line-level fields (amounts, tax codes, quantities, units) come entirely from
    the SAP PO response so they always match what SAP expects.
    Header fields (invoice number, date, total) come from the extracted invoice.
    """
    po_number: str = extracted.get("po_number") or ""
    invoice_no: str = extracted.get("invoice_no") or ""
    invoice_date: str = extracted.get("invoice_date") or _today_ddmmyyyy()
    currency: str = extracted.get("currency") or sap_po.CURRENCY or "INR"
    gross_amount: float = _safe_float(extracted.get("gross_amount") or 0)
    today = _today_ddmmyyyy()

    item_data: list[MIROItemData] = []

    for idx, sap_line in enumerate(sap_po.PO_LINE_ITEMS):
        invoice_doc_no = f"{(idx + 1) * 10:06d}"

        # GRN reference from first GRN entry for this SAP line
        reference_no = ""
        reference_document_year = str(datetime.now(UTC).year)
        reference_doc_it = ""
        if sap_line.GRN:
            first_grn = sap_line.GRN[0]
            reference_no = first_grn.GR_NUMBER.strip()
            reference_document_year = _gr_year(first_grn.GR_DATE)
            reference_doc_it = first_grn.GR_ITEM_NUMBER.strip()

        # Tax code exactly from SAP PO; V0 (zero-rate) for lines with no tax code
        tax_code = sap_line.TAX_CODE.strip()  # blank for zero-tax lines

        # Amounts from SAP PO — guarantees they match SAP's records
        item_amount = _safe_float(sap_line.NET_AMOUNT)
        gross_line = _safe_float(sap_line.GROSS_AMOUNT)
        quantity = _safe_float(sap_line.ORDERED_QUANTITY)
        po_unit = sap_line.UOM.strip() or "EA"
        sap_item_number = sap_line.ITEM_NUMBER.strip()

        item_data.append(
            MIROItemData(
                invoice_document_no=invoice_doc_no,
                po_number=po_number,
                po_item=sap_item_number,
                reference_no=reference_no,
                reference_document_year=reference_document_year,
                reference_doc_it=reference_doc_it,
                tax_code=tax_code,
                item_amount=item_amount,
                quantity=quantity,
                po_unit=po_unit,
                tax_amount=0,
            )
        )

    miro_data = MIROData(
        document_date=invoice_date,
        posting_date=today,
        reference_document_no=po_number,
        company_code=sap_po.COM_CODE.strip(),
        currency=currency,
        gross_amount=gross_amount,
        calc_tax_ind=_CALC_TAX_IND,
        payment_terms=_DEFAULT_PAYMENT_TERMS,
        baseline_date=today,
        business_place=sap_po.BUYER_ID.strip(),
        item_data=item_data,
    )

    log.info("MIRO payload built", po_number=po_number, invoice_no=invoice_no, line_count=len(item_data))
    return MIROPayload(data=[miro_data])
