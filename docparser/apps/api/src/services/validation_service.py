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
    sap_lines = sap_po.PO_LINE_ITEMS

    # Build lookup: SAP uses "10","20","30" format; invoices often use "1","2","3"
    # Support both: exact match first, then positional fallback
    sap_line_map = {item.ITEM_NUMBER.strip(): item for item in sap_lines}

    def _find_sap_line(line_num: str, idx: int):
        """Match by exact item number, zero-padded SAP number, or position."""
        if line_num in sap_line_map:
            return sap_line_map[line_num]
        # Try SAP-style: "1" → "10", "2" → "20"
        sap_style = str(int(line_num) * 10) if line_num.isdigit() else ""
        if sap_style and sap_style in sap_line_map:
            return sap_line_map[sap_style]
        # Try zero-padded: "1" → "00001" or "000010"
        for key in sap_line_map:
            if key.lstrip("0") == line_num.lstrip("0"):
                return sap_line_map[key]
        # Positional fallback: use nth SAP line
        if idx < len(sap_lines):
            return sap_lines[idx]
        return None

    lines_ok = 0
    gr_status_list: list[dict[str, Any]] = []

    for idx, inv_line in enumerate(inv_lines):
        line_num = str(inv_line.get("line_number") or str(idx + 1)).strip()
        sap_line = _find_sap_line(line_num, idx)
        line_has_mismatch = False

        if sap_line is None:
            mismatches.append(_mismatch(f"line_items[{line_num}]", line_num, "NOT_FOUND", "warning"))
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

        # GR status — use RECEIVED_QUANTITY from line if no GRN entries
        inv_qty = _dec(inv_line.get("quantity", "0"))
        if sap_line is not None:
            if sap_line.GRN:
                total_gr_qty = sum(_dec(grn.GR_QUANTITY) for grn in sap_line.GRN)
                gr_docs = [grn.GR_NUMBER for grn in sap_line.GRN if grn.GR_NUMBER]
            else:
                # No GRN entries — use RECEIVED_QUANTITY from PO line
                total_gr_qty = _dec(sap_line.RECEIVED_QUANTITY)
                gr_docs = []
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
    # Consider valid if PO was found (has PO_NUMBER) and overall score ≥ 0.60
    po_found = bool(sap_po.PO_NUMBER)
    is_valid = po_found and overall_confidence >= 0.60

    recommendation = (
        "Document is approved for MIRO posting." if is_valid
        else "Document requires manual review before posting." if overall_confidence >= 0.40
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
        "fetched_at": datetime.now(UTC).isoformat(),
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
        "fetched_at": datetime.now(UTC).isoformat(),
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


# ---------------------------------------------------------------------------
# Service PO workflow — two hard gates, both must pass before posting is allowed
#
#   Gate A  SES presence    — zpo_grn/Detail must return an SES for every line
#   Gate B  PO line ceiling — invoiced qty/amount must be ≤ the PO line figures
#
# Availability against previously posted invoices is deliberately NOT checked here.
# The only endpoint that reports it (ZSPO_VALD/SERV_PO_VAL) also creates the MIRO,
# so it belongs to the posting step — see post_service_po_lines below.
#
# These are confidence-scored for material POs; for service POs they are hard
# blocks — an invoice failing either must never reach the posting step.
# ---------------------------------------------------------------------------


def _norm_item(value: Any) -> str:
    """Normalise a PO item number for map lookups — "00010", "10" and "0010" all
    describe the same line, so compare on the unpadded numeric form."""
    clean = str(value or "").strip()
    return clean.lstrip("0") or "0" if clean.isdigit() else clean.upper()


def check_service_po_ses(sap_po: SAPPOResponse, extracted: dict[str, Any]) -> dict[str, Any]:
    """Gate A — every invoiced line must have an approved SES on the PO.

    SES is the service-PO equivalent of a goods receipt: zpo_grn/Detail returns it
    in each line's GRN[] block. No SES means the service was never confirmed as
    delivered, so the invoice cannot be posted regardless of the amounts.
    """
    inv_lines: list[dict[str, Any]] = extracted.get("line_items") or []
    sap_line_map = {_norm_item(item.ITEM_NUMBER): item for item in sap_po.PO_LINE_ITEMS}

    entries: list[dict[str, Any]] = []
    missing: list[str] = []

    for inv_line in inv_lines:
        line_num = str(inv_line.get("line_number") or "").strip()
        sap_line = sap_line_map.get(_norm_item(line_num))
        ses_numbers = [
            g.ses_number for g in (sap_line.GRN if sap_line else []) if g.ses_number
        ]
        if not ses_numbers:
            missing.append(line_num)

        entries.append({
            "line_number":  line_num,
            "po_item":      line_num,
            "ses_numbers":  ses_numbers,
            "gr_documents": ses_numbers,   # keeps the existing gr_status UI shape
            "total_gr_qty": float(_dec(sap_line.RECEIVED_QUANTITY)) if sap_line else 0.0,
            "invoice_qty":  float(_dec(inv_line.get("quantity", "0"))),
            "status":       "complete" if ses_numbers else "missing",
        })

    return {
        "lines":        entries,
        "missing_ses":  missing,
        "all_have_ses": len(missing) == 0 and len(entries) > 0,
    }


def check_service_po_ceilings(
    extracted: dict[str, Any], sap_po: SAPPOResponse
) -> dict[str, Any]:
    """Gate B — invoiced quantity and amount must not exceed the PO line figures.

    Equal is fine (full invoice), less is fine (partial invoice, balance stays
    open); greater is a hard fail. Gate C re-checks this against what prior
    invoices already consumed, but failing here means the invoice is wrong on the
    face of the PO itself and is worth reporting separately.
    """
    inv_lines: list[dict[str, Any]] = extracted.get("line_items") or []
    sap_line_map = {_norm_item(item.ITEM_NUMBER): item for item in sap_po.PO_LINE_ITEMS}

    results: list[dict[str, Any]] = []
    violations: list[dict[str, str]] = []

    for inv_line in inv_lines:
        line_num = str(inv_line.get("line_number") or "").strip()
        sap_line = sap_line_map.get(_norm_item(line_num))
        inv_qty = _dec(inv_line.get("quantity", "0"))
        inv_amt = _dec(inv_line.get("amount", "0"))

        if sap_line is None:
            violations.append(_mismatch(f"line[{line_num}]", line_num, "NOT_FOUND_ON_PO", "error"))
            results.append({
                "po_item": line_num, "invoice_qty": float(inv_qty),
                "invoice_amount": float(inv_amt), "po_qty": 0.0, "po_amount": 0.0,
                "within_po": False, "reason": "Line item not found on the PO",
            })
            continue

        po_qty = _dec(sap_line.ORDERED_QUANTITY)
        # Compare like with like. The extracted line `amount` is the gross for
        # that line (tax included), so it belongs against the PO line's GROSS,
        # not its NET: on an 18% GST line, 8,260 gross against 7,000 net looks
        # like a 1,260 overrun when the two figures in fact agree exactly.
        po_amt = _dec(sap_line.GROSS_AMOUNT) or _dec(sap_line.NET_AMOUNT)
        reason = ""

        if inv_qty > po_qty + Decimal("0.000001"):
            reason = f"Invoiced quantity {inv_qty} exceeds PO quantity {po_qty}"
            violations.append(_mismatch(f"line[{line_num}].quantity", str(inv_qty), str(po_qty), "error"))
        elif inv_amt > po_amt + Decimal("0.01"):
            reason = f"Invoiced amount {inv_amt} exceeds PO line total {po_amt}"
            violations.append(_mismatch(f"line[{line_num}].amount", str(inv_amt), str(po_amt), "error"))

        results.append({
            "po_item": line_num,
            "invoice_qty": float(inv_qty), "invoice_amount": float(inv_amt),
            "po_qty": float(po_qty), "po_amount": float(po_amt),
            "within_po": not reason, "reason": reason,
        })

    return {
        "lines": results,
        "violations": violations,
        "all_within_po": not violations and len(results) > 0,
    }


async def post_service_po_lines(
    extracted: dict[str, Any],
    po_number: str,
    company_code: str = "",
    already_posted: dict[str, str] | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """Post the Service PO invoice, line by line, via ZSPO_VALD/SERV_PO_VAL.

    WARNING — side-effecting. That endpoint validates against the PO *and* creates
    the MIRO document in one call, so this belongs to the posting step only. It is
    never called during validation and never retried: a repeat call would post a
    second invoice.

    SAP is the authority here — it re-checks availability itself, which is why the
    validation step no longer duplicates that check.

    `already_posted` maps po_item → MIRO number for lines a previous attempt got
    through. Posting is per line, so a multi-line invoice can partially succeed;
    those lines are skipped on a retry instead of being posted a second time.
    """
    from src.services.sap_service import get_sap_service

    sap_service = get_sap_service(tenant_id)
    lines: list[dict[str, Any]] = extracted.get("line_items") or []
    posted_before = {_norm_item(k): v for k, v in (already_posted or {}).items() if v}

    results: list[dict[str, Any]] = []
    blocking_reasons: list[str] = []
    miro_numbers: list[str] = []
    all_posted = True

    for line in lines:
        po_item = str(line.get("line_number") or "").strip()
        invoice_qty = _dec(line.get("quantity", "0"))
        # SERV_PO_VAL nets invoice_amount against AVAILABLE_NET, so it wants the
        # line's taxable value, not its gross. Sending the gross on an 18% GST
        # line overstates the invoice by the tax and reads as an overrun.
        invoice_amount = _dec(line.get("taxable_amount", "0")) or _dec(line.get("amount", "0"))

        prior_miro = posted_before.get(_norm_item(po_item))
        if prior_miro:
            # Already posted by an earlier attempt — posting again would duplicate
            # the invoice in SAP.
            log.info("skipping already-posted service PO line",
                     po_item=po_item, miro_number=prior_miro)
            miro_numbers.append(prior_miro)
            results.append({
                "po_item": po_item, "validation_status": "SKIPPED",
                "miro_status": "SUCCESS", "message": f"Already posted as {prior_miro}",
                "case": "full", "posted": True, "miro_number": prior_miro,
                "skipped": True, "blocking_reason": "",
                "invoice_qty": float(invoice_qty), "invoice_amount": float(invoice_amount),
            })
            continue

        try:
            resp = await sap_service.post_service_po_line(
                po_number=po_number,
                po_item=po_item,
                invoice_qty=float(invoice_qty),
                invoice_amount=float(invoice_amount),
                company_code=company_code,
            )
        except Exception as exc:
            # The call may or may not have posted before failing — say so plainly
            # rather than guessing, and never retry it automatically.
            all_posted = False
            reason = (
                f"Line {po_item}: SAP call failed — {exc}. "
                "Check in SAP whether a MIRO was created before re-posting."
            )
            blocking_reasons.append(reason)
            log.error("service PO line posting errored", po_item=po_item, error=str(exc))
            results.append({
                "po_item": po_item, "validation_status": "ERROR", "miro_status": "UNKNOWN",
                "message": str(exc), "case": "rejected", "posted": False,
                "miro_number": "", "blocking_reason": reason,
                "invoice_qty": float(invoice_qty), "invoice_amount": float(invoice_amount),
            })
            continue

        if resp.succeeded:
            miro_numbers.append(resp.miro_number)
        else:
            all_posted = False
            blocking_reasons.append(f"Line {po_item}: {resp.blocking_reason}")

        results.append({
            "po_item":           po_item,
            "validation_status": resp.VALIDATION_STATUS or resp.STATUS,
            "miro_status":       resp.MIRO_STATUS,
            "message":           resp.message,
            "case":              resp.consumption_case,
            "posted":            resp.succeeded,
            "miro_number":       resp.miro_number,
            "fiscal_year":       resp.FISCAL_YEAR,
            "invoice_qty":       resp.INVOICE_QTY,
            "invoice_amount":    resp.INVOICE_AMOUNT,
            "total_qty":         resp.TOTAL_QTY,
            "total_net":         resp.TOTAL_NET,
            "consumed_qty":      resp.CONSUMED_QTY,
            "consumed_net":      resp.CONSUMED_NET,
            "available_qty":     resp.AVAILABLE_QTY,
            "available_net":     resp.AVAILABLE_NET,
            "remaining_qty":     resp.remaining_qty,
            "remaining_net":     resp.remaining_net,
            "blocking_reason":   resp.blocking_reason,
        })

    if not results:
        blocking_reasons.append("No line items were extracted from the invoice")
        all_posted = False

    cases = [r["case"] for r in results]
    overall_case = (
        "rejected" if "rejected" in cases
        else "full"    if cases and all(c == "full" for c in cases)
        else "partial" if cases
        else "none"
    )

    log.info(
        "service PO posting complete",
        po_number=po_number,
        line_count=len(results),
        case=overall_case,
        miro_numbers=miro_numbers,
        all_posted=all_posted,
    )

    return {
        "posted_at": datetime.now(UTC).isoformat(),
        "lines": results,
        "case": overall_case,
        "blocking_reasons": blocking_reasons,
        "miro_numbers": miro_numbers,
        "miro_number": miro_numbers[0] if miro_numbers else "",
        "all_posted": all_posted and len(results) > 0,
    }


async def validate_service_po_invoice(
    extracted: dict[str, Any],
    sap_po: SAPPOResponse,
    po_number: str,
) -> dict[str, Any]:
    """Full Service PO validation — runs the header/vendor scoring plus all three
    hard gates, and returns the standard validation result dict with `is_valid`
    reflecting every gate.

    `is_valid` is what the MIRO step keys off, so it is only ever True when the
    SES exists, the invoice fits inside the PO line, and SAP confirms the amounts
    are still available.

    Scoring is deliberately *not* delegated to the material-PO validator: that one
    compares invoice unit price against PO unit price and invoice gross against PO
    gross, both of which legitimately differ on a partial service invoice (billing
    4,000 against an 8,000 service line is normal, not a mismatch).
    """
    ses_check      = check_service_po_ses(sap_po, extracted)
    ceiling_check  = check_service_po_ceilings(extracted, sap_po)

    mismatches: list[dict[str, str]] = []

    # ── Header scoring — vendor identity plus an amount *ceiling* check ───
    inv_gstin = (extracted.get("vendor_gstin") or "").strip().upper()
    sap_gstin = sap_po.VENDOR_GSTIN.strip().upper()
    if inv_gstin and sap_gstin:
        gstin_score = 1.0 if inv_gstin == sap_gstin else 0.0
        if gstin_score == 0.0:
            mismatches.append(_mismatch("vendor_gstin", inv_gstin, sap_gstin, "error"))
    else:
        gstin_score = 0.5   # nothing to compare — neither credit nor penalty

    vendor_ratio = _ratio(extracted.get("vendor_name") or "", sap_po.VENDOR_NAME)
    if vendor_ratio < 0.80:
        mismatches.append(_mismatch("vendor_name", extracted.get("vendor_name") or "",
                                    sap_po.VENDOR_NAME, "error" if vendor_ratio < 0.50 else "warning"))

    # A partial invoice is expected to be *under* the PO gross — only an overrun matters.
    inv_gross = _dec(extracted.get("gross_amount", "0"))
    sap_gross = _dec(sap_po.GROSS_AMOUNT)
    if inv_gross <= sap_gross + Decimal("0.01"):
        amount_score = 1.0
    else:
        amount_score = 0.0
        mismatches.append(_mismatch("gross_amount", str(inv_gross), str(sap_gross), "error"))

    header_confidence = gstin_score * 0.30 + vendor_ratio * 0.30 + amount_score * 0.40

    # ── Line and SES scoring come straight from the gates ─────────────────
    ceiling_lines = ceiling_check["lines"]
    line_confidence = (
        sum(1 for line in ceiling_lines if line["within_po"]) / len(ceiling_lines)
        if ceiling_lines else 0.0
    )
    ses_lines = ses_check["lines"]
    gr_confidence = (
        sum(1 for line in ses_lines if line["status"] == "complete") / len(ses_lines)
        if ses_lines else 0.0
    )
    overall_confidence = header_confidence * 0.40 + line_confidence * 0.40 + gr_confidence * 0.20

    result: dict[str, Any] = {
        "fetched_at":           datetime.now(UTC).isoformat(),
        "po_data":              sap_po.raw_response,
        "header_confidence":    round(header_confidence, 4),
        "line_item_confidence": round(line_confidence, 4),
        "gr_confidence":        round(gr_confidence, 4),
        "overall_confidence":   round(overall_confidence, 4),
        "is_valid":             overall_confidence >= 0.70,
    }

    result["ses_validation"]        = ses_check
    result["po_ceiling_validation"] = ceiling_check
    result["gr_status"]             = ses_check["lines"]

    # Surface gate failures as mismatches so the existing UI renders them.
    for line_num in ses_check["missing_ses"]:
        mismatches.append(_mismatch(f"line[{line_num}].ses", "MISSING", "SES_REQUIRED", "error"))
    mismatches.extend(ceiling_check["violations"])
    result["mismatches"] = mismatches

    # Availability against prior invoices is *not* checked here: the only endpoint
    # that reports it (ZSPO_VALD/SERV_PO_VAL) also posts the MIRO, so calling it
    # during validation would post the invoice. SAP re-checks it at posting time.
    gates = {
        "ses_present":    ses_check["all_have_ses"],
        "within_po_line": ceiling_check["all_within_po"],
    }
    result["gates"] = gates
    all_gates_passed = all(gates.values())

    result["is_valid"] = bool(result.get("is_valid", False)) and all_gates_passed

    if not gates["ses_present"]:
        result["recommendation"] = (
            "No approved SES found for "
            f"line(s) {', '.join(ses_check['missing_ses']) or '—'} — "
            "the service must be confirmed in SAP before this invoice can be posted."
        )
    elif not gates["within_po_line"]:
        result["recommendation"] = (
            "Invoiced quantity/amount exceeds the PO line — do not post to SAP."
        )
    elif all_gates_passed and result["is_valid"]:
        result["recommendation"] = (
            "Service PO validated — ready to post. SAP performs the final availability "
            "check and creates the MIRO in the same step."
        )

    log.info(
        "service PO invoice validation complete",
        po_number=po_number,
        gates=gates,
        is_valid=result["is_valid"],
    )
    return result
