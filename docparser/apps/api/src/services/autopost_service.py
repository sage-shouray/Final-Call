"""Auto-post gating — decides whether a document may post to SAP unattended.

Posting to SAP is irreversible from this application's side, so the burden of
proof sits with auto-posting: every gate must pass, and any gate that cannot be
evaluated counts as a failure rather than being skipped.

When a gate fails the document is not rejected — it is handed to a human with
the specific reason, so the reviewer knows what to look at instead of re-checking
the whole invoice.

Disabled by default (`AUTO_POST_ENABLED`). Removing human approval from a
financial posting is a control decision, not a technical one.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

import structlog

from src.config import settings
from src.services.routing_service import Route

log = structlog.get_logger(__name__)


def _dec(value: Any) -> Decimal:
    try:
        return Decimal(str(value).strip().replace(",", "") or "0")
    except (InvalidOperation, AttributeError):
        return Decimal("0")


def _gate(name: str, passed: bool, detail: str = "") -> dict[str, Any]:
    return {"gate": name, "passed": passed, "detail": detail}


# Two kinds of gate, and the difference decides who may override what.
#
# Most gates express policy or confidence: the extraction was blurry, the value
# is above the ceiling for unattended posting, the sender is not on the vendor
# allowlist. A reviewer looking at the invoice can reasonably say "I have read
# it, it is correct, post it" — that is what review is for.
#
# These four are different. Each one means the invoice contradicts what SAP
# already holds: a different vendor, more than the PO authorises, a different
# tax treatment, or an invoice already posted once. No amount of human
# confidence makes those safe, because the disagreement is with the purchase
# order, not with the reader. Posting anyway puts a document in the ledger that
# does not reconcile, which is the failure this system exists to prevent.
#
# So these block every posting path, automatic and manual alike. The way past
# one is to correct the invoice or the PO and re-validate — never to approve.
BLOCKING_GATES = frozenset({
    "vendor_match",
    "within_po_value",
    "tax_matches_po",
    "not_duplicate",
    "segmentation_confidence",
})


async def blocking_failures(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """Gates that disagree with SAP and must stop any posting.

    Returns the failing gates with their detail text, so the caller can tell the
    user exactly which figure disagrees rather than "validation failed".

    Evaluated independently of AUTO_POST_ENABLED: the gates are computed the
    same way whether or not unattended posting is switched on, because this
    question is about the data, not about the automation policy.
    """
    result = await evaluate(doc)
    return [
        g for g in result["gates"]
        if g["gate"] in BLOCKING_GATES and not g["passed"]
    ]


def _po_tax_rate(po_data: dict[str, Any]) -> Decimal | None:
    """Tax rate the PO expects, derived from its own figures.

    Deliberately not read from TAX_CODE: the code is a customising key ("R1")
    whose rate lives in SAP, differs per client, and would need a mapping table
    this application does not own. Gross minus net over net is the same number
    without the lookup.

    Summed over the lines rather than taken from the header, because the header
    NET_AMOUNT comes back as 0.00 on some POs while the lines carry the value.
    """
    lines = po_data.get("PO_LINE_ITEMS") or []
    net = sum((_dec(li.get("NET_AMOUNT")) for li in lines), Decimal("0"))
    gross = sum((_dec(li.get("GROSS_AMOUNT")) for li in lines), Decimal("0"))
    if not net:
        net = _dec(po_data.get("NET_AMOUNT"))
        gross = _dec(po_data.get("GROSS_AMOUNT"))
    if net <= 0 or gross <= 0:
        return None
    return (gross - net) / net


def _invoice_tax_rate(extracted: dict[str, Any]) -> Decimal | None:
    """Tax rate actually charged on the invoice.

    Prefers the explicit tax components; falls back to gross minus taxable for
    invoices where the model reported a total without the breakdown.
    """
    taxable = _dec(extracted.get("taxable_amount"))
    if taxable <= 0:
        return None
    components = sum(
        (_dec(extracted.get(f)) for f in
         ("cgst_amount", "sgst_amount", "igst_amount", "cess_amount")),
        Decimal("0"),
    )
    tax = components if components > 0 else _dec(extracted.get("gross_amount")) - taxable
    if tax < 0:
        return None
    return tax / taxable


async def evaluate(doc: dict[str, Any]) -> dict[str, Any]:
    """Decide whether `doc` may post automatically.

    Returns the full gate list either way — the UI shows passes as reassurance
    and failures as the review checklist.
    """
    extracted: dict[str, Any] = doc.get("extracted") or {}
    pipeline: dict[str, Any] = doc.get("pipeline") or {}
    routing: dict[str, Any] = pipeline.get("routing") or {}

    gates: list[dict[str, Any]] = []

    # ── 0. Split out of a multi-invoice PDF with a confident boundary ──────
    # A document that came from segmentation_service splitting a merged PDF
    # carries its boundary confidence in source_metadata. A low-confidence
    # boundary means the page range for this document may be wrong — it could
    # be missing a page of its own invoice or include one from the next —
    # which posts the wrong amount to SAP. No reviewer confidence fixes a
    # mis-drawn page boundary, so this blocks every posting path exactly like
    # a SAP data mismatch, not just the unattended one.
    seg = (doc.get("source_metadata") or {}).get("segmentation") or {}
    if seg:
        forced = bool(seg.get("forced_manual_review"))
        gates.append(_gate(
            "segmentation_confidence", not forced,
            f"Split from a multi-invoice PDF ({seg.get('reason', '')})."
            if forced else
            "Split from a multi-invoice PDF with a confident boundary "
            f"(invoice {seg.get('invoice_no') or '—'}, PO {seg.get('po_number') or '—'}).",
        ))
    else:
        gates.append(_gate("segmentation_confidence", True, "Not split from a multi-invoice PDF."))

    # ── 1. Routing resolved and actionable ────────────────────────────────
    route = routing.get("route") or ""
    route_ok = bool(routing.get("resolved")) and route != Route.HOLD.value
    gates.append(_gate(
        "route_resolved",
        route_ok,
        f"Routed to {route}." if route_ok
        else (routing.get("reason") or "Routing did not complete."),
    ))

    # ── 2. OCR confidence ─────────────────────────────────────────────────
    confidence = float(extracted.get("confidence_score") or 0.0)
    gates.append(_gate(
        "extraction_confidence",
        confidence >= settings.AUTO_POST_MIN_CONFIDENCE,
        f"Extraction confidence {confidence:.0%} "
        f"(minimum {settings.AUTO_POST_MIN_CONFIDENCE:.0%}).",
    ))

    # ── 3. Vendor identity matches the PO ─────────────────────────────────
    inv_gstin = (extracted.get("vendor_gstin") or "").strip().upper()
    sap_gstin = (routing.get("vendor_gstin") or "").strip().upper()
    if route == Route.FB60.value:
        gates.append(_gate("vendor_match", True, "Non-PO invoice — no PO vendor to match."))
    elif inv_gstin and sap_gstin:
        gates.append(_gate(
            "vendor_match", inv_gstin == sap_gstin,
            f"Invoice GSTIN {inv_gstin} vs PO vendor {sap_gstin}.",
        ))
    else:
        gates.append(_gate(
            "vendor_match", False,
            "Vendor GSTIN missing on the invoice or the PO — cannot confirm the vendor.",
        ))

    # ── 4. Invoice value within the PO ────────────────────────────────────
    # A ceiling, not an equality check: a partial delivery legitimately invoices
    # less than the PO authorises. The wording says so, because "1,000 vs 1,180 —
    # passed" otherwise reads as though the two had been found to agree.
    inv_gross = _dec(extracted.get("gross_amount"))
    po_data = routing.get("po_data") or {}
    po_gross = _dec(po_data.get("GROSS_AMOUNT"))
    if route == Route.FB60.value:
        gates.append(_gate("within_po_value", True, "Non-PO invoice — no PO ceiling."))
    else:
        gates.append(_gate(
            "within_po_value", bool(po_gross) and inv_gross <= po_gross + Decimal("0.01"),
            f"Invoice {inv_gross:,.2f} is within the PO ceiling of {po_gross:,.2f}."
            if po_gross and inv_gross <= po_gross + Decimal("0.01")
            else f"Invoice {inv_gross:,.2f} exceeds the PO value of {po_gross:,.2f}."
            if po_gross else "PO carries no gross value — cannot check the ceiling.",
        ))

    # ── 4b. Tax treatment agrees with the PO ──────────────────────────────
    # The ceiling above is blind to a pure tax discrepancy: an invoice claiming
    # exemption on a taxable PO is *under* the ceiling and sails through, then
    # posts a tax difference into SAP. Quantity and price can match perfectly
    # while the tax code does not.
    #
    # Compared as a rate rather than an amount, so the check is independent of
    # how much was delivered — a half-shipment at the same tax code still agrees.
    if route == Route.FB60.value:
        gates.append(_gate("tax_matches_po", True, "Non-PO invoice — no PO tax code to match."))
    else:
        po_rate = _po_tax_rate(po_data)
        inv_rate = _invoice_tax_rate(extracted)
        if po_rate is None or inv_rate is None:
            gates.append(_gate(
                "tax_matches_po", False,
                "Cannot determine the tax rate on the invoice or the PO — "
                "a tax difference would post unchecked.",
            ))
        else:
            # Half a percentage point absorbs rounding on split CGST/SGST lines
            # without admitting a genuine rate difference (the smallest real gap
            # between Indian GST slabs is 5 points).
            agrees = abs(po_rate - inv_rate) <= Decimal("0.005")
            gates.append(_gate(
                "tax_matches_po", agrees,
                f"Tax rate {inv_rate:.1%} on the invoice matches the PO."
                if agrees else
                f"Invoice is taxed at {inv_rate:.1%} but the PO expects "
                f"{po_rate:.1%} — the difference is tax, not quantity or price.",
            ))

    # ── 5. Goods receipt / service entry confirmed ────────────────────────
    # Read against the route, not in isolation. On migo_then_miro the missing GR
    # is what the action exists to post, so treating it as a blocker would mean
    # no such document could ever be processed automatically — the opposite of
    # the single-action design. A missing GR only blocks when the route claims
    # one is already there (miro_direct), or when only SAP can create it (SES).
    confirmed = bool((routing.get("confirmation") or {}).get("all_confirmed"))
    if route == Route.FB60.value:
        gates.append(_gate("receipt_confirmed", True, "Non-PO invoice — no GR required."))
    elif route == Route.MIGO_THEN_MIRO.value:
        gates.append(_gate(
            "receipt_confirmed", True,
            "Goods receipt will be posted as part of this action.",
        ))
    else:
        gates.append(_gate(
            "receipt_confirmed", confirmed,
            "GR/SES confirmed on all lines." if confirmed
            else "Awaiting goods receipt or service entry sheet.",
        ))

    # ── 6. Emailed documents must come from a known sender ────────────────
    # A mailbox address becomes public the moment it is shared with vendors, so
    # anyone can post a PDF into it. An emailed invoice therefore only qualifies
    # for unattended posting when its sender is on the tenant's allowlist AND
    # that mailbox is configured to automate — both decided at ingestion time.
    if (doc.get("source") or "web") == "email":
        meta = doc.get("source_metadata") or {}
        sender = meta.get("sender_trusted")
        allowed = bool(meta.get("auto_post_allowed"))
        gates.append(_gate(
            "email_sender_trusted", allowed,
            "Sender is on the allowlist and this mailbox may post automatically."
            if allowed else (
                "Emailed by an unrecognised sender — needs review."
                if sender is False
                else "This mailbox is not configured for unattended posting."
            ),
        ))

    # ── 7. Not a duplicate ────────────────────────────────────────────────
    duplicate_of = await _find_duplicate(doc, extracted)
    gates.append(_gate(
        "not_duplicate", duplicate_of is None,
        f"Invoice already processed as {duplicate_of}." if duplicate_of
        else "No previous posting found for this invoice.",
    ))

    # ── 8. Value ceiling — high-value invoices always get a human ─────────
    # A ceiling of 0 turns the value limit off entirely: any amount may post
    # unattended, and the remaining gates carry the whole burden of correctness.
    ceiling = _dec(settings.AUTO_POST_MAX_AMOUNT)
    within_ceiling = ceiling <= 0 or inv_gross <= ceiling
    if ceiling <= 0:
        detail = "No value limit — any amount may post automatically."
    elif within_ceiling:
        detail = f"Within the auto-post ceiling ({ceiling:,.2f})."
    else:
        detail = f"Invoice {inv_gross:,.2f} exceeds the auto-post ceiling of {ceiling:,.2f}."
    gates.append(_gate("within_auto_post_ceiling", within_ceiling, detail))

    failed = [g["gate"] for g in gates if not g["passed"]]
    enabled = settings.AUTO_POST_ENABLED
    auto_post = enabled and not failed

    if not enabled:
        decision = "manual_approval_required"
        summary = "Auto-posting is disabled — this document needs approval before posting."
    elif auto_post:
        decision = "auto_post"
        summary = "All checks passed — posting automatically."
    else:
        decision = "manual_approval_required"
        summary = f"{len(failed)} check(s) need review before posting."

    log.info(
        "auto-post evaluated",
        document_id=doc.get("document_id"),
        decision=decision,
        failed_gates=failed,
        enabled=enabled,
    )

    return {
        "decision":     decision,
        "auto_post":    auto_post,
        "enabled":      enabled,
        "gates":        gates,
        "failed_gates": failed,
        "summary":      summary,
        "route":        route,
    }


async def _find_duplicate(doc: dict[str, Any], extracted: dict[str, Any]) -> str | None:
    """Return the document_id of an earlier posting of this same invoice, if any.

    Matching on vendor + invoice number rather than PO number: one PO legitimately
    carries several invoices, but the same invoice number from the same vendor
    twice is a re-upload. Without this, auto-posting would double-pay.
    """
    invoice_no = (extracted.get("invoice_no") or "").strip().upper()
    vendor_gstin = (extracted.get("vendor_gstin") or "").strip().upper()
    if not invoice_no:
        return None

    from sqlalchemy import select

    from src.database import AsyncSessionLocal
    from src.models.document import DocumentRow

    async with AsyncSessionLocal() as session:
        stmt = (
            select(DocumentRow.document_id, DocumentRow.extracted)
            .where(
                DocumentRow.id != doc.get("id"),
                DocumentRow.miro_posting.isnot(None),
            )
            .order_by(DocumentRow.uploaded_at.desc())
            .limit(500)
        )
        for other_id, other_extracted in (await session.execute(stmt)).all():
            other = other_extracted or {}
            if (other.get("invoice_no") or "").strip().upper() != invoice_no:
                continue
            other_gstin = (other.get("vendor_gstin") or "").strip().upper()
            if vendor_gstin and other_gstin and vendor_gstin != other_gstin:
                continue
            return str(other_id)

    return None
