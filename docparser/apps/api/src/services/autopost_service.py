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


async def evaluate(doc: dict[str, Any]) -> dict[str, Any]:
    """Decide whether `doc` may post automatically.

    Returns the full gate list either way — the UI shows passes as reassurance
    and failures as the review checklist.
    """
    extracted: dict[str, Any] = doc.get("extracted") or {}
    pipeline: dict[str, Any] = doc.get("pipeline") or {}
    routing: dict[str, Any] = pipeline.get("routing") or {}

    gates: list[dict[str, Any]] = []

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
    inv_gross = _dec(extracted.get("gross_amount"))
    po_gross = _dec((routing.get("po_data") or {}).get("GROSS_AMOUNT"))
    if route == Route.FB60.value:
        gates.append(_gate("within_po_value", True, "Non-PO invoice — no PO ceiling."))
    else:
        gates.append(_gate(
            "within_po_value", bool(po_gross) and inv_gross <= po_gross + Decimal("0.01"),
            f"Invoice {inv_gross:,.2f} vs PO {po_gross:,.2f}.",
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
