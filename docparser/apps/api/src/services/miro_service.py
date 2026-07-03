"""MIRO payload builder — transforms extracted invoice + SAP PO/GRN data into ZMIRO payload."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog

from src.schemas.sap import (
    MIROData, MIROItemData, MIROPayload, SAPPOResponse,
    SAPServicePOResponse, ServiceMIROData, ServiceMIROItemData, ServiceMIROPayload,
)

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


def build_service_miro_payload(
    extracted: dict[str, Any],
    sap_service_po: SAPServicePOResponse,
    validation: dict[str, Any],
) -> ServiceMIROPayload:
    """Build the Service PO MIRO payload for zmiro_post/MIRO endpoint.

    Key differences from material MIRO:
    - Uses sheet_no (SES number) in each line item
    - tax_amount included per line (not zero)
    - reference_no = SES entry number from GRN list
    """
    po_number: str = sap_service_po.PO_NUMBER or extracted.get("po_number") or ""
    invoice_no: str = extracted.get("invoice_no") or ""
    invoice_date: str = extracted.get("invoice_date") or _today_ddmmyyyy()
    currency: str = extracted.get("currency") or sap_service_po.CURRENCY or "INR"
    gross_amount: float = _safe_float(extracted.get("gross_amount") or 0)
    today = _today_ddmmyyyy()

    # Map extracted line items by index for amount/tax fallback
    extracted_lines: list[dict[str, Any]] = extracted.get("line_items") or []

    item_data: list[ServiceMIROItemData] = []

    for idx, sap_line in enumerate(sap_service_po.PO_LINE_ITEMS):
        invoice_doc_no = f"{(idx + 1) * 10:06d}"

        # Pull SES data from GRN list (populated when SES is approved)
        sheet_no = ""
        reference_no = ""
        reference_document_year = str(datetime.now(UTC).year)
        reference_doc_it = "0001"
        if sap_line.GRN:
            first_ses = sap_line.GRN[0]
            sheet_no = first_ses.SES_NUMBER
            reference_no = first_ses.ENTRY_NO
            reference_document_year = first_ses.YEAR or reference_document_year
            reference_doc_it = first_ses.ITEM or "0001"

        tax_code = sap_line.TAX_CODE.strip()
        item_amount = _safe_float(sap_line.NET_AMOUNT)
        quantity = _safe_float(sap_line.ORDERED_QUANTITY)
        po_unit = sap_line.UOM.strip() or "AU"

        # Tax amount: prefer from extracted line item, fall back to SAP gross - net
        tax_amount = 0.0
        if idx < len(extracted_lines):
            tax_amount = _safe_float(extracted_lines[idx].get("tax_amount") or 0)
        if not tax_amount:
            tax_amount = _safe_float(sap_line.GROSS_AMOUNT) - item_amount

        item_data.append(ServiceMIROItemData(
            invoice_document_no=invoice_doc_no,
            po_number=po_number,
            po_item=sap_line.ITEM_NUMBER.strip(),
            reference_no=reference_no,
            reference_document_year=reference_document_year,
            reference_doc_it=reference_doc_it,
            tax_code=tax_code,
            item_amount=item_amount,
            quantity=quantity,
            po_unit=po_unit,
            tax_amount=tax_amount,
            sheet_no=sheet_no,
        ))

    miro_data = ServiceMIROData(
        document_date=invoice_date,
        posting_date=today,
        reference_document_no=invoice_no,
        company_code=sap_service_po.COM_CODE.strip(),
        currency=currency,
        gross_amount=gross_amount,
        payment_terms=_DEFAULT_PAYMENT_TERMS,
        baseline_date=today,
        item_data=item_data,
    )

    log.info(
        "Service MIRO payload built",
        po_number=po_number,
        invoice_no=invoice_no,
        line_count=len(item_data),
        ses_approved=sap_service_po.ses_approved,
    )
    return ServiceMIROPayload(data=[miro_data])


def build_freight_miro_payload(
    extracted: dict[str, Any],
    sap_po: SAPPOResponse,
    validation: dict[str, Any],
) -> ServiceMIROPayload:
    """Build Freight Invoice MIRO payload for zmiro_post/MIRO endpoint.

    Validates via zpo_grn/Detail (same as material PO), but posts to zmiro_post/MIRO
    (same as service PO). sheet_no is always empty for freight; reference_no = GR_NUMBER.
    """
    po_number: str = extracted.get("po_number") or sap_po.PO_NUMBER or ""
    invoice_no: str = extracted.get("invoice_no") or ""
    invoice_date: str = extracted.get("invoice_date") or _today_ddmmyyyy()
    currency: str = extracted.get("currency") or sap_po.CURRENCY or "INR"
    gross_amount: float = _safe_float(extracted.get("gross_amount") or 0)
    today = _today_ddmmyyyy()

    extracted_lines: list[dict[str, Any]] = extracted.get("line_items") or []
    item_data: list[ServiceMIROItemData] = []

    for idx, sap_line in enumerate(sap_po.PO_LINE_ITEMS):
        invoice_doc_no = f"{(idx + 1) * 10:06d}"

        reference_no = ""
        reference_document_year = str(datetime.now(UTC).year)
        reference_doc_it = "0001"
        if sap_line.GRN:
            first_grn = sap_line.GRN[0]
            reference_no = first_grn.GR_NUMBER.strip()
            reference_document_year = _gr_year(first_grn.GR_DATE)
            reference_doc_it = first_grn.GR_ITEM_NUMBER.strip() or "0001"

        tax_code = sap_line.TAX_CODE.strip()
        item_amount = _safe_float(sap_line.NET_AMOUNT)
        quantity = _safe_float(sap_line.ORDERED_QUANTITY)
        po_unit = sap_line.UOM.strip() or "AU"

        tax_amount = 0.0
        if idx < len(extracted_lines):
            tax_amount = _safe_float(extracted_lines[idx].get("tax_amount") or 0)
        if not tax_amount:
            tax_amount = _safe_float(sap_line.GROSS_AMOUNT) - item_amount

        item_data.append(ServiceMIROItemData(
            invoice_document_no=invoice_doc_no,
            po_number=po_number,
            po_item=sap_line.ITEM_NUMBER.strip(),
            reference_no=reference_no,
            reference_document_year=reference_document_year,
            reference_doc_it=reference_doc_it,
            tax_code=tax_code,
            item_amount=item_amount,
            quantity=quantity,
            po_unit=po_unit,
            tax_amount=tax_amount,
            sheet_no="",  # no SES for freight — GR is auto-posted
        ))

    miro_data = ServiceMIROData(
        document_date=invoice_date,
        posting_date=today,
        reference_document_no=invoice_no,
        company_code=sap_po.COM_CODE.strip(),
        currency=currency,
        gross_amount=gross_amount,
        payment_terms=_DEFAULT_PAYMENT_TERMS,
        baseline_date=today,
        item_data=item_data,
    )

    log.info("Freight MIRO payload built", po_number=po_number, invoice_no=invoice_no, line_count=len(item_data))
    return ServiceMIROPayload(data=[miro_data])
