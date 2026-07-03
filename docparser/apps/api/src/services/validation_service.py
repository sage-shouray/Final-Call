"""Invoice-vs-PO validation using fuzzy matching and weighted scoring.

Scoring model
─────────────
  header_score (weights sum to 1.0)
    • vendor_gstin  exact match            30 %
    • gross_amount  within ±1.00           30 %
    • vendor_name   difflib ratio ≥ 0.80   20 %
    • ship_to_name  difflib ratio ≥ 0.75   20 %

  line_score  = % of line items with zero mismatches
  gr_score    = % of line items where GR quantity ≥ invoice quantity

  overall = (header × 0.4) + (line × 0.4) + (gr × 0.2)
  is_valid = overall ≥ 0.70
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
from typing import Any

import structlog

from src.schemas.sap import SAPPOResponse, SAPServicePOResponse

log = structlog.get_logger(__name__)


def _ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.strip().lower(), b.strip().lower()).ratio()


def _dec(value: Any) -> Decimal:
    try:
        clean = str(value).strip().replace(",", "")
        return Decimal(clean)
    except InvalidOperation:
        return Decimal("0")


def _mismatch(field: str, extracted_value: str, sap_value: str, severity: str = "error") -> dict[str, str]:
    return {"field": field, "extracted_value": str(extracted_value), "sap_value": str(sap_value), "severity": severity}


async def validate_invoice_against_po(
    extracted: dict[str, Any],
    sap_po: SAPPOResponse,
) -> dict[str, Any]:
    mismatches: list[dict[str, str]] = []
    header_scores: dict[str, float] = {}

    # ── vendor_gstin — exact match (30%) ──────────────────────────────────
    inv_gstin = (extracted.get("vendor_gstin") or "").strip().upper()
    sap_gstin = sap_po.VENDOR_GSTIN.strip().upper()
    if inv_gstin and sap_gstin and inv_gstin == sap_gstin:
        header_scores["gstin"] = 1.0
    else:
        header_scores["gstin"] = 0.0
        if inv_gstin != sap_gstin:
            mismatches.append(_mismatch("vendor_gstin", inv_gstin, sap_gstin, "error"))

    # ── gross_amount — within ±1.00 (30%) ────────────────────────────────
    inv_amount = _dec(extracted.get("gross_amount", "0"))
    sap_amount = _dec(sap_po.GROSS_AMOUNT)
    amount_diff = abs(inv_amount - sap_amount)
    if amount_diff <= Decimal("1.00"):
        header_scores["amount"] = 1.0
    else:
        header_scores["amount"] = max(0.0, float(1 - amount_diff / max(sap_amount, Decimal("1"))))
        mismatches.append(_mismatch("gross_amount", str(inv_amount), str(sap_amount), "error"))

    # ── vendor_name — fuzzy ≥ 0.80 (20%) ─────────────────────────────────
    inv_vendor = extracted.get("vendor_name") or ""
    sap_vendor = sap_po.VENDOR_NAME
    vendor_ratio = _ratio(inv_vendor, sap_vendor)
    header_scores["vendor"] = vendor_ratio
    if vendor_ratio < 0.80:
        mismatches.append(_mismatch("vendor_name", inv_vendor, sap_vendor,
                                    "error" if vendor_ratio < 0.50 else "warning"))

    # ── ship_to_name — fuzzy ≥ 0.75 (20%) ───────────────────────────────
    inv_ship = extracted.get("ship_to_name") or ""
    sap_ship = sap_po.SHIP_TO_NAME
    ship_ratio = _ratio(inv_ship, sap_ship)
    header_scores["ship"] = ship_ratio
    if ship_ratio < 0.75:
        mismatches.append(_mismatch("ship_to_name", inv_ship, sap_ship,
                                    "error" if ship_ratio < 0.40 else "warning"))

    header_confidence = (
        header_scores["gstin"] * 0.30
        + header_scores["amount"] * 0.30
        + header_scores["vendor"] * 0.20
        + header_scores["ship"] * 0.20
    )

    # ── Line-item checks ──────────────────────────────────────────────────
    inv_lines: list[dict[str, Any]] = extracted.get("line_items") or []
    sap_line_map = {item.ITEM_NUMBER.strip(): item for item in sap_po.PO_LINE_ITEMS}

    lines_ok = 0
    gr_status_list: list[dict[str, Any]] = []

    for inv_line in inv_lines:
        line_num = str(inv_line.get("line_number") or "").strip()
        sap_line = sap_line_map.get(line_num)
        line_has_mismatch = False

        if sap_line is None:
            mismatches.append(_mismatch(f"line_items[{line_num}]", line_num, "NOT_FOUND", "error"))
            line_has_mismatch = True
        else:
            # material_code
            inv_mat = (inv_line.get("material_code") or "").strip().upper()
            sap_mat = sap_line.MATERIAL_CODE.strip().upper()
            if inv_mat and sap_mat and inv_mat != sap_mat:
                mismatches.append(_mismatch(f"line[{line_num}].material_code", inv_mat, sap_mat, "warning"))
                line_has_mismatch = True

            # unit_price — within ±0.50
            inv_price = _dec(inv_line.get("unit_rate", "0"))
            sap_price = _dec(sap_line.UNIT_PRICE)
            if abs(inv_price - sap_price) > Decimal("0.50"):
                mismatches.append(_mismatch(f"line[{line_num}].unit_price", str(inv_price), str(sap_price), "error"))
                line_has_mismatch = True

        if not line_has_mismatch:
            lines_ok += 1

        # GR status
        inv_qty = _dec(inv_line.get("quantity", "0"))
        if sap_line is not None:
            total_gr_qty = sum(_dec(grn.GR_QUANTITY) for grn in sap_line.GRN)
            gr_docs = [grn.GR_NUMBER for grn in sap_line.GRN if grn.GR_NUMBER]
            gr_status = "complete" if total_gr_qty >= inv_qty else ("partial" if total_gr_qty > 0 else "missing")
        else:
            total_gr_qty = Decimal("0")
            gr_docs = []
            gr_status = "missing"

        gr_status_list.append({
            "line_number": line_num,
            "po_item": line_num,
            "gr_documents": gr_docs,
            "total_gr_qty": float(total_gr_qty),
            "invoice_qty": float(inv_qty),
            "status": gr_status,
        })

    total_lines = len(inv_lines)
    line_confidence = (lines_ok / total_lines) if total_lines else 1.0
    gr_confidence = (
        sum(1 for g in gr_status_list if g["status"] in {"complete", "partial"}) / total_lines
        if total_lines else 1.0
    )

    overall_confidence = (
        header_confidence * 0.40
        + line_confidence * 0.40
        + gr_confidence * 0.20
    )
    is_valid = overall_confidence >= 0.70

    recommendation = (
        "Document is approved for MIRO posting." if is_valid
        else "Document requires manual review before posting." if overall_confidence >= 0.50
        else "Document has critical mismatches — do not post to SAP."
    )

    log.info(
        "validation complete",
        overall=round(overall_confidence, 3),
        header=round(header_confidence, 3),
        line=round(line_confidence, 3),
        gr=round(gr_confidence, 3),
        mismatches=len(mismatches),
        is_valid=is_valid,
    )

    return {
        "fetched_at": datetime.now(UTC),
        "po_data": sap_po.raw_response,
        "header_confidence": round(header_confidence, 4),
        "line_item_confidence": round(line_confidence, 4),
        "gr_confidence": round(gr_confidence, 4),
        "overall_confidence": round(overall_confidence, 4),
        "mismatches": mismatches,
        "gr_status": gr_status_list,
        "is_valid": is_valid,
        "recommendation": recommendation,
    }


async def validate_service_invoice_against_po(
    extracted: dict[str, Any],
    sap_spo: SAPServicePOResponse,
) -> dict[str, Any]:
    """Validate a Service PO invoice against SAP zspodetail data.

    Simpler than material PO — no GR quantity checks.
    Key check: SES must be approved (GRN list non-empty).
    """
    mismatches: list[dict[str, str]] = []

    # ── Vendor name match (40%) ───────────────────────────────────────────
    inv_vendor = extracted.get("vendor_name") or ""
    sap_vendor = sap_spo.VENDOR_NAME
    vendor_ratio = _ratio(inv_vendor, sap_vendor)
    if vendor_ratio < 0.80:
        mismatches.append(_mismatch("vendor_name", inv_vendor, sap_vendor,
                                    "error" if vendor_ratio < 0.50 else "warning"))

    # ── Gross amount match ±1.00 (40%) ───────────────────────────────────
    inv_amount = _dec(extracted.get("gross_amount", "0"))
    sap_amount = _dec(sap_spo.GROSS_AMOUNT)
    amount_diff = abs(inv_amount - sap_amount)
    amount_score = 1.0 if amount_diff <= Decimal("1.00") else max(0.0, float(1 - amount_diff / max(sap_amount, Decimal("1"))))
    if amount_diff > Decimal("1.00"):
        mismatches.append(_mismatch("gross_amount", str(inv_amount), str(sap_amount), "error"))

    # ── SES approved check (20%) ─────────────────────────────────────────
    ses_score = 1.0 if sap_spo.ses_approved else 0.0

    header_confidence = vendor_ratio * 0.40 + amount_score * 0.40 + ses_score * 0.20

    # ── Service line checks ───────────────────────────────────────────────
    inv_lines: list[dict[str, Any]] = extracted.get("line_items") or []
    sap_line_map = {item.ITEM_NUMBER.strip(): item for item in sap_spo.PO_LINE_ITEMS}

    lines_ok = 0
    ses_status_list: list[dict[str, Any]] = []

    for inv_line in inv_lines:
        line_num = str(inv_line.get("line_number") or "").strip()
        sap_line = sap_line_map.get(line_num)
        line_has_mismatch = False

        if sap_line is None:
            mismatches.append(_mismatch(f"line_items[{line_num}]", line_num, "NOT_FOUND", "warning"))
            line_has_mismatch = True
        else:
            # Service description match
            inv_desc = (inv_line.get("description") or "").strip()
            sap_desc = sap_line.DESCRIPTION.strip()
            desc_ratio = _ratio(inv_desc, sap_desc)
            if desc_ratio < 0.60:
                mismatches.append(_mismatch(f"line[{line_num}].description", inv_desc, sap_desc, "warning"))
                line_has_mismatch = True

        if not line_has_mismatch:
            lines_ok += 1

        ses_entry = sap_line.GRN[0] if (sap_line and sap_line.GRN) else None
        ses_status_list.append({
            "line_number": line_num,
            "po_item": line_num,
            "gr_documents": [ses_entry.SES_NUMBER] if ses_entry else [],
            "total_gr_qty": float(_dec(sap_line.RECEIVED_QUANTITY)) if sap_line else 0.0,
            "invoice_qty": float(_dec(inv_line.get("quantity", "0"))),
            "status": "complete" if ses_entry else "missing",
        })

    total_lines = len(inv_lines)
    line_confidence = (lines_ok / total_lines) if total_lines else 1.0
    gr_confidence = ses_score  # for service PO, GR confidence = SES approved

    overall_confidence = (
        header_confidence * 0.50
        + line_confidence * 0.30
        + gr_confidence * 0.20
    )
    is_valid = overall_confidence >= 0.60  # slightly lower threshold for service PO

    recommendation = (
        "Service PO approved for MIRO posting." if is_valid
        else "Service PO requires review before posting." if overall_confidence >= 0.40
        else "Service PO has critical mismatches — do not post to SAP."
    )

    log.info(
        "service PO validation complete",
        overall=round(overall_confidence, 3),
        ses_approved=sap_spo.ses_approved,
        mismatches=len(mismatches),
        is_valid=is_valid,
    )

    return {
        "fetched_at": datetime.now(UTC),
        "po_data": sap_spo.raw_response,
        "header_confidence": round(header_confidence, 4),
        "line_item_confidence": round(line_confidence, 4),
        "gr_confidence": round(gr_confidence, 4),
        "overall_confidence": round(overall_confidence, 4),
        "mismatches": mismatches,
        "gr_status": ses_status_list,
        "is_valid": is_valid,
        "recommendation": recommendation,
    }
