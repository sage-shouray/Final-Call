"""Route execution — the step that acts on what routing decided.

`routing_service` works out where a document must go; this runs it. A material
PO whose goods receipt is missing gets the GR posted and then the invoice, in
one action, so "invoice or GRN" is no longer a choice the user makes.

Everything here is a chain of the existing workers rather than a reimplementation
of them, so the single-step paths keep behaving exactly as they do today.

Partial failure is the thing to get right: a GR that succeeds is real inventory
movement in SAP. If the invoice then fails, the document must resume from the
invoice step and never re-post the GR.
"""
from datetime import UTC, datetime
from typing import Any

import structlog

log = structlog.get_logger(__name__)


class ProcessBlocked(Exception):
    """Raised when the route cannot be executed and a human must intervene."""

    def __init__(self, reason: str, detail: str = "ROUTE_BLOCKED") -> None:
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


def _route_of(doc: dict[str, Any]) -> str:
    return ((doc.get("pipeline") or {}).get("routing") or {}).get("route") or ""


def _gr_already_posted(doc: dict[str, Any]) -> bool:
    """True if a previous attempt already created the goods receipt.

    Checked before every GR post so a retry after a failed invoice step does not
    duplicate stock movement.
    """
    grn = doc.get("grn_posting") or {}
    return grn.get("status") == "success" and bool(grn.get("grn_number"))


def _miro_already_posted(doc: dict[str, Any]) -> bool:
    miro = doc.get("miro_posting") or {}
    return miro.get("status") == "success" and bool(miro.get("miro_number"))


async def run_process_direct(document_id: str, posted_by: str = "system") -> dict[str, Any]:
    """Execute the route SAP chose for this document.

    Returns a summary dict describing what was done. Raises ProcessBlocked when
    the route is not executable (held, or an FB60 that needs its form).
    """
    from src.database import AsyncSessionLocal
    from src.models.document import DocumentStatus
    from src.repositories.document_repository import DocumentRepository
    from src.services.routing_service import Route
    from src.workers.migo_worker import run_migo_direct
    from src.workers.sap_worker import run_miro_direct, run_validation_direct

    bound_log = log.bind(document_id=document_id)

    async with AsyncSessionLocal() as session:
        doc = await DocumentRepository(session).find_by_document_id(document_id)
    if not doc:
        raise ProcessBlocked(f"Document '{document_id}' not found", "DOCUMENT_NOT_FOUND")

    route = _route_of(doc)
    routing = (doc.get("pipeline") or {}).get("routing") or {}
    steps: list[str] = []

    if not route:
        raise ProcessBlocked(
            "This document has not been routed yet — re-run processing first.",
            "NOT_ROUTED",
        )

    if route == Route.HOLD.value:
        raise ProcessBlocked(
            routing.get("reason") or "This document needs attention before it can be posted.",
            "ROUTE_HOLD",
        )

    if route == Route.FB60.value:
        # Non-PO invoices need G/L account and cost assignment that only a human
        # can supply, so there is nothing to chain here.
        raise ProcessBlocked(
            "Non-PO invoice — complete the FB60 form to post it.",
            "FB60_FORM_REQUIRED",
        )

    if _miro_already_posted(doc):
        raise ProcessBlocked(
            f"Already posted as MIRO {(doc.get('miro_posting') or {}).get('miro_number')}.",
            "ALREADY_POSTED",
        )

    # ── Step 1: goods receipt, when the route calls for one ────────────────
    if route == Route.MIGO_THEN_MIRO.value:
        if _gr_already_posted(doc):
            grn_no = (doc.get("grn_posting") or {}).get("grn_number")
            bound_log.info("GR already posted — resuming at the invoice step", grn_number=grn_no)
            steps.append(f"GR {grn_no} (already posted, skipped)")
        else:
            bound_log.info("route requires a goods receipt — posting MIGO first")
            await run_migo_direct(document_id, posted_by)

            async with AsyncSessionLocal() as session:
                doc = await DocumentRepository(session).find_by_document_id(document_id) or doc
            if not _gr_already_posted(doc):
                grn = doc.get("grn_posting") or {}
                raise ProcessBlocked(
                    grn.get("message") or "Goods receipt could not be posted — invoice not attempted.",
                    "GR_FAILED",
                )
            steps.append(f"GR {(doc.get('grn_posting') or {}).get('grn_number')}")

    # ── Step 2: validate against SAP ───────────────────────────────────────
    # The invoice step reads sap_validation (Service PO refuses to post without
    # its gates), so make sure it exists rather than assuming a human ran it.
    if not doc.get("sap_validation"):
        bound_log.info("no validation on file — validating before posting")
        await run_validation_direct(document_id)
        async with AsyncSessionLocal() as session:
            doc = await DocumentRepository(session).find_by_document_id(document_id) or doc
        steps.append("validated")

    validation = doc.get("sap_validation") or {}
    if not validation.get("is_valid", False):
        raise ProcessBlocked(
            validation.get("recommendation") or "SAP validation did not pass — invoice not posted.",
            "VALIDATION_FAILED",
        )

    # ── Step 3: invoice ────────────────────────────────────────────────────
    # run_miro_direct re-reads the PO, so a GR posted moments ago is picked up
    # with its new document number.
    bound_log.info("posting invoice", route=route)
    await run_miro_direct(document_id, posted_by)

    async with AsyncSessionLocal() as session:
        doc = await DocumentRepository(session).find_by_document_id(document_id) or doc

    miro = doc.get("miro_posting") or {}
    posted = miro.get("status") == "success"
    if posted:
        steps.append(f"MIRO {miro.get('miro_number')}")

    result = {
        "document_id": document_id,
        "route":       route,
        "posted":      posted,
        "steps":       steps,
        "miro_number": miro.get("miro_number", ""),
        "grn_number":  (doc.get("grn_posting") or {}).get("grn_number", ""),
        "finished_at": datetime.now(UTC).isoformat(),
    }
    bound_log.info("route execution complete", **{k: v for k, v in result.items() if k != "document_id"})

    if not posted:
        # The GR (if any) stands; only the invoice failed. Status is already back
        # at VALIDATED, so a retry resumes at the invoice step.
        async with AsyncSessionLocal() as session:
            repo = DocumentRepository(session)
            fresh = await repo.find_by_document_id(document_id)
            if fresh:
                await repo.update_status(fresh["id"], DocumentStatus.VALIDATED, error_entry={
                    "stage": "process", "detail": "MIRO_FAILED",
                    "message": "Invoice posting failed; any goods receipt already posted was kept.",
                    "timestamp": datetime.now(UTC).isoformat(),
                })
                await session.commit()

    return result
