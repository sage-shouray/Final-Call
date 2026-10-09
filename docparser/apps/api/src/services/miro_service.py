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


def _gr_reference(sap_line: Any) -> tuple[str, str, str]:
    """The goods-receipt reference for one line: (REF_DOC, REF_DOC_YEAR, REF_DOC_IT).

    All three or none. They identify the material document an invoice line is
    matched against, and SAP only accepts them when the PO line carries GR-based
    invoice verification (EKPO-WEBRE). Sending a partial set fails twice over:

        Enter goods receipt data only when working with GR-based IV
        Fill in mandatory field REF_DOC, REF_DOC_YEAR, REF_DOC_IT

    — the first because any GR data at all is wrong on a non-GR-based line, the
    second because having supplied one field, SAP requires the other two.

    That is what happened: the year defaulted to the current year while the
    other two defaulted to empty, so every MIRO against a PO with no goods
    receipt sent "2026" on its own and was rejected.

    Keyed on GR_NUMBER rather than on the GRN block being present, because a
    service line carries an SES number in SSES_NO and leaves GR_NUMBER empty —
    a truthy GRN block with nothing usable in it.
    """
    for grn in (getattr(sap_line, "GRN", None) or []):
        number = (grn.GR_NUMBER or "").strip()
        # All-zeros is SAP's way of saying "no document", not a document id.
        if number and number.strip("0"):
            return number, _gr_year(grn.GR_DATE), (grn.GR_ITEM_NUMBER or "").strip()
    return "", "", ""


def _real_grns(sap_line: Any) -> list[Any]:
    """Every goods receipt actually posted against this line (not a placeholder)."""
    return [
        grn for grn in (getattr(sap_line, "GRN", None) or [])
        if (grn.GR_NUMBER or "").strip().strip("0")
    ]


def _match_invoice_line(
    sap_item_number: str, idx: int, inv_lines: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Find the extracted invoice line that corresponds to a given PO line.

    Same matching rules validation_service uses (exact, SAP-style ×10, or
    positional fallback), so a line that validated against a PO item also
    posts against that same line here rather than quietly drifting apart.
    """
    norm = sap_item_number.lstrip("0") or sap_item_number
    for li in inv_lines:
        ln = str(li.get("line_number") or "").strip()
        if not ln:
            continue
        if ln == sap_item_number or ln.lstrip("0") == norm:
            return li
        if ln.isdigit() and str(int(ln) * 10) == sap_item_number:
            return li
    return inv_lines[idx] if idx < len(inv_lines) else None


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

    inv_lines: list[dict[str, Any]] = extracted.get("line_items") or []
    item_data: list[MIROItemData] = []
    seq = 0  # counts actual MIRO lines emitted, not PO lines — a split-GR line emits more than one

    for idx, sap_line in enumerate(sap_po.PO_LINE_ITEMS):
        tax_code = sap_line.TAX_CODE.strip()  # blank for zero-tax lines
        po_unit = sap_line.UOM.strip() or "EA"
        sap_item_number = sap_line.ITEM_NUMBER.strip()
        line_net = _safe_float(sap_line.NET_AMOUNT)
        line_qty = _safe_float(sap_line.ORDERED_QUANTITY)
        unit_rate = (line_net / line_qty) if line_qty else 0.0

        # What THIS invoice actually bills on this line — not what the PO
        # ordered. A full-delivery invoice (the common case) specifies the
        # same quantity as the PO and this changes nothing; a partial invoice
        # specifies less, and posting the PO's full quantity instead would
        # leave the line items totalling more than the invoice's own header
        # gross amount — exactly the mismatch that produces "Balance not zero".
        inv_line = _match_invoice_line(sap_item_number, idx, inv_lines)
        invoiced_qty = _safe_float(inv_line.get("quantity")) if inv_line else 0.0
        qty_to_post = (
            invoiced_qty if 0 < invoiced_qty < line_qty - 1e-6 else line_qty
        )

        grns = _real_grns(sap_line)

        if not grns:
            # Not GR-based — no reference, post whatever quantity this invoice
            # actually bills (full net amount only when billing the full line,
            # otherwise price × quantity so partial lines don't overstate it).
            amount = line_net if qty_to_post >= line_qty - 1e-6 else round(unit_rate * qty_to_post, 2)
            seq += 1
            item_data.append(MIROItemData(
                invoice_document_no=f"{seq * 10:06d}",
                po_number=po_number, po_item=sap_item_number,
                reference_no="", reference_document_year="", reference_doc_it="",
                tax_code=tax_code, item_amount=amount, quantity=qty_to_post,
                po_unit=po_unit, tax_amount=0,
            ))
            continue

        # GR-based — one MIRO line per GR actually consumed by this invoice,
        # each referencing its own GR number and carrying only the quantity
        # taken from that GR. Confirmed with SAP MM: never pick one GR
        # arbitrarily while invoicing the full (or a partial) line — the GR
        # reference and that line's quantity must agree. GRs are consumed in
        # order until the invoiced quantity is used up, so a full invoice
        # against a split receipt still emits one line per GR (as before),
        # and a partial invoice consumes only as many GRs as it actually covers.
        remaining = qty_to_post
        for grn in grns:
            if remaining <= 1e-9:
                break
            gr_qty = _safe_float(grn.GR_QUANTITY)
            take = min(gr_qty, remaining)
            amount = round(unit_rate * take, 2)
            seq += 1
            item_data.append(MIROItemData(
                invoice_document_no=f"{seq * 10:06d}",
                po_number=po_number, po_item=sap_item_number,
                reference_no=grn.GR_NUMBER.strip(),
                reference_document_year=_gr_year(grn.GR_DATE),
                reference_doc_it=(grn.GR_ITEM_NUMBER or "").strip(),
                tax_code=tax_code, item_amount=amount, quantity=take,
                po_unit=po_unit, tax_amount=0,
            ))
            remaining -= take
        # remaining > 0 here means the invoice bills more than any known GR
        # covers — that disagreement is what the receipt-confirmed / value
        # gates upstream exist to catch before this payload is ever built, so
        # it is not re-litigated here.

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

        # As above — the "0001" default made this worse, sending two of the
        # three fields on a line that should carry none.
        reference_no, reference_document_year, reference_doc_it = _gr_reference(sap_line)
        if reference_no and not reference_doc_it:
            reference_doc_it = "0001"

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
