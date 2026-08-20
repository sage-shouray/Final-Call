"""SAP-driven document routing — the stage that replaces the manual type picker.

The user used to tell us whether an invoice was Material PO, Service PO or Non-PO.
They were reading it off the paper and could be wrong, which sent documents down
the wrong workflow with nothing to catch it.

SAP already knows for certain. Given a PO number, `zpo_grn/Detail` reports the
line type (ZSER = service), whether a GR is expected, and whether the GR/SES has
been posted. So routing is derived from facts rather than a human's reading, and
carries no confidence score — only the extracted field data does.

This module is strictly read-only against SAP. It must never call
ZSPO_VALD/SERV_PO_VAL, which posts a MIRO as a side effect.
"""
from __future__ import annotations

import asyncio
import time
from enum import StrEnum
from typing import Any

import structlog

from src.config import settings
from src.models.document import InvoiceSubtype, TCode
from src.schemas.sap import SAPPOResponse

log = structlog.get_logger(__name__)


class Route(StrEnum):
    """What should happen to this document next."""
    MIRO_DIRECT     = "miro_direct"      # GR/SES already done — invoice can post
    MIGO_THEN_MIRO  = "migo_then_miro"   # material PO awaiting GR — post GR, then invoice
    FB60            = "fb60"             # no PO — non-PO invoice, posts to G/L
    HOLD            = "hold"             # needs a human before anything can proceed


_SERVICE_LINE_TYPE = "ZSER"


def _is_service_po(sap_po: SAPPOResponse) -> bool:
    """A PO is a service PO when any line is typed ZSER.

    TYPE lives on the raw line payload rather than SAPPOLineItem, so read it from
    raw_response — the parsed schema predates service-PO support.
    """
    for raw_line in (sap_po.raw_response.get("PO_LINE_ITEMS") or []):
        if str(raw_line.get("TYPE") or "").strip().upper() == _SERVICE_LINE_TYPE:
            return True
    return False


def _confirmation_status(sap_po: SAPPOResponse, is_service: bool) -> dict[str, Any]:
    """Per-line GR (material) / SES (service) status.

    Material lines confirm via GRN[].GR_NUMBER; service lines via GRN[].SSES_NO —
    on a service PO GR_NUMBER comes back empty, which is why the two are read
    from different fields.
    """
    lines: list[dict[str, Any]] = []
    missing: list[str] = []

    for line in sap_po.PO_LINE_ITEMS:
        item = line.ITEM_NUMBER.strip()
        docs = [grn.ses_number for grn in line.GRN if grn.ses_number]
        gr_expected = str(
            next(
                (
                    raw.get("GR_EXPECTED", "")
                    for raw in (sap_po.raw_response.get("PO_LINE_ITEMS") or [])
                    if str(raw.get("ITEM_NUMBER", "")).strip() == item
                ),
                "",
            )
        ).strip()

        confirmed = bool(docs)
        if not confirmed:
            missing.append(item)

        lines.append({
            "po_item":     item,
            "confirmed":   confirmed,
            "documents":   docs,
            "gr_expected": gr_expected,
            "kind":        "SES" if is_service else "GR",
        })

    return {"lines": lines, "missing": missing, "all_confirmed": not missing and bool(lines)}


def _sap_answered(exc: BaseException) -> bool:
    """True if SAP replied and rejected the request, rather than being unreachable.

    The SAP client wraps both cases in SAPConnectionError, so the two are told
    apart by whether a real HTTP response came back. It matters: an unreachable
    server is transient and worth retrying automatically, while "Invalid PO /
    Vendor" (returned as HTTP 500 with a body) is a permanent business answer
    that needs a human to correct the PO number. Reporting the second as the
    first would leave the document waiting for a recovery that never comes.
    """
    return "SAP returned HTTP" in str(exc)


async def classify(
    po_candidates: list[str],
    *,
    invoice_no: str = "",
) -> dict[str, Any]:
    """Resolve a document's route from SAP.

    Tries each PO candidate in order and stops at the first SAP recognises, so a
    mis-picked number costs one read-only call rather than a wrong posting.
    Returns a plain dict for JSONB storage on the document row.
    """
    from src.services.sap_service import get_sap_service

    started = time.perf_counter()

    def _result(**kwargs: Any) -> dict[str, Any]:
        return {"elapsed_ms": round((time.perf_counter() - started) * 1000, 1), **kwargs}

    # ── No PO on the document → non-PO invoice, posts straight to G/L ──────
    if not po_candidates:
        log.info("routed as non-PO — no PO number found")
        return _result(
            route=Route.FB60.value,
            invoice_subtype=InvoiceSubtype.NON_PO.value,
            tcode=TCode.FB60.value,
            po_number="",
            resolved=True,
            reason="No PO number found on the document — treated as a non-PO invoice.",
        )

    sap_service = get_sap_service()
    tried: list[str] = []
    lookup_errors: list[str] = []
    rejected: list[str] = []

    for candidate in po_candidates:
        tried.append(candidate)
        try:
            # Bounded: routing degrades gracefully when SAP is down, so waiting
            # out the client's retry backoff buys nothing and stalls the fast track.
            async with asyncio.timeout(settings.PIPELINE_SAP_TIMEOUT_SECONDS):
                sap_po = await sap_service.fetch_po_details(candidate)
        except TimeoutError:
            log.warning("PO lookup timed out", po_number=candidate,
                        timeout_s=settings.PIPELINE_SAP_TIMEOUT_SECONDS)
            lookup_errors.append(
                f"{candidate}: no response within {settings.PIPELINE_SAP_TIMEOUT_SECONDS}s"
            )
            continue
        except Exception as exc:
            # SAP being unreachable is not the same as the PO not existing —
            # keep them apart so an outage is never reported as a bad PO number,
            # and a bad PO number is never reported as an outage.
            if _sap_answered(exc):
                log.info("PO rejected by SAP", po_number=candidate, error=str(exc))
                rejected.append(candidate)
            else:
                log.warning("PO lookup failed", po_number=candidate, error=str(exc))
                lookup_errors.append(f"{candidate}: {exc}")
            continue

        if not (sap_po.PO_NUMBER.strip() and sap_po.PO_LINE_ITEMS):
            log.info("PO not recognised by SAP", po_number=candidate)
            continue

        # ── Recognised — SAP now tells us everything about the route ───────
        is_service = _is_service_po(sap_po)
        confirmation = _confirmation_status(sap_po, is_service)
        subtype = InvoiceSubtype.SERVICE_PO if is_service else InvoiceSubtype.PO

        if confirmation["all_confirmed"]:
            route, reason = Route.MIRO_DIRECT, (
                f"{'SES' if is_service else 'GR'} confirmed on all lines — ready to invoice."
            )
        elif is_service:
            # An SES can only be created in SAP; we cannot post it from here.
            route, reason = Route.HOLD, (
                f"No approved SES on line(s) {', '.join(confirmation['missing'])} — "
                "the service entry sheet must be created in SAP first."
            )
        else:
            route, reason = Route.MIGO_THEN_MIRO, (
                f"No GR on line(s) {', '.join(confirmation['missing'])} — "
                "post the goods receipt first, then the invoice."
            )

        log.info(
            "routed from SAP",
            po_number=sap_po.PO_NUMBER.strip(),
            subtype=subtype.value,
            route=route.value,
            attempts=len(tried),
        )

        return _result(
            route=route.value,
            invoice_subtype=subtype.value,
            tcode=TCode.MIRO.value,
            po_number=sap_po.PO_NUMBER.strip(),
            resolved=True,
            is_service=is_service,
            confirmation=confirmation,
            company_code=sap_po.COM_CODE.strip(),
            vendor_name=sap_po.VENDOR_NAME.strip(),
            vendor_gstin=sap_po.VENDOR_GSTIN.strip(),
            po_data=sap_po.raw_response,
            candidates_tried=tried,
            reason=reason,
        )

    # ── Nothing resolved. Distinguish "SAP was down" from "PO doesn't exist" ──
    if lookup_errors:
        # Transient: the document is fine, we just couldn't ask. Worth retrying
        # automatically rather than putting it in front of a human.
        log.error("SAP unreachable during routing", candidates=tried, errors=lookup_errors)
        return _result(
            route=Route.HOLD.value,
            invoice_subtype="",
            tcode="",
            po_number="",
            resolved=False,
            sap_unavailable=True,
            retryable=True,
            candidates_tried=tried,
            lookup_errors=lookup_errors,
            reason=(
                "Could not reach SAP to identify this PO — routing is incomplete. "
                "This will resolve once SAP is reachable; no action needed on the invoice."
            ),
        )

    # Permanent: SAP answered and does not recognise the number. Retrying cannot
    # change that, so send it to a human instead of parking it indefinitely.
    log.warning("no PO candidate resolved in SAP", candidates=tried, rejected=rejected)
    return _result(
        route=Route.HOLD.value,
        invoice_subtype="",
        tcode="",
        po_number="",
        resolved=False,
        sap_unavailable=False,
        retryable=False,
        candidates_tried=tried,
        rejected_by_sap=rejected,
        reason=(
            f"SAP does not recognise PO number(s) {', '.join(tried)} — "
            "check the PO number on the invoice before posting."
        ),
    )
