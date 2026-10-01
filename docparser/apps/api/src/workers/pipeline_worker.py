"""Ingest pipeline — runs the fast routing track alongside the OCR track.

Two tracks start together the moment a file lands:

    fast track   page-1 text (~29 ms) → PO/invoice number → SAP lookup (~800 ms)
                 → route: material or service, GR/SES done or not
    OCR track    Gemini reads the whole invoice (~17.5 s) → 45+ fields

The fast track finishes roughly 16 seconds before OCR, so by the time the field
data lands the route and the SAP PO payload are already cached on the document.
That removes both the manual type picker and the serial SAP round-trip that used
to run after validation.

The two tracks write to different columns (`pipeline` vs `extracted`/`status`)
through separate sessions, so they never contend.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import structlog

from src.config import settings

log = structlog.get_logger(__name__)


async def _persist(document_id: str, patch: dict[str, Any]) -> None:
    """Merge a patch into the document's `pipeline` column."""
    from src.database import AsyncSessionLocal
    from src.repositories.document_repository import DocumentRepository

    async with AsyncSessionLocal() as session:
        repo = DocumentRepository(session)
        doc = await repo.find_by_document_id(document_id)
        if not doc:
            return
        pipeline = dict(doc.get("pipeline") or {})
        pipeline.update(patch)
        await repo.update(doc["id"], {"pipeline": pipeline})
        await session.commit()


async def _fast_track(document_id: str, file_bytes: bytes, tenant_id: str | None = None) -> dict[str, Any]:
    """Identity scrape then SAP routing. Persists each step as it completes."""
    from src.services.identity_service import extract_identity
    from src.services.routing_service import classify

    identity = await extract_identity(file_bytes)
    await _persist(document_id, {"identity": identity})

    routing = await classify(
        identity["po_candidates"], invoice_no=identity.get("invoice_no", ""),
        tenant_id=tenant_id,
    )
    await _persist(document_id, {"routing": routing})

    # Apply the subtype the moment routing resolves — roughly a second in, rather
    # than waiting ~17 s for OCR. This is what lets the UI show the route while
    # extraction is still running.
    if settings.PIPELINE_ROUTING_AUTHORITATIVE and routing.get("invoice_subtype"):
        from src.database import AsyncSessionLocal
        from src.repositories.document_repository import DocumentRepository

        async with AsyncSessionLocal() as session:
            repo = DocumentRepository(session)
            doc = await repo.find_by_document_id(document_id)
            if doc:
                updates: dict[str, Any] = {"invoice_subtype": routing["invoice_subtype"]}
                if routing.get("tcode"):
                    updates["tcode"] = routing["tcode"]
                await repo.update(doc["id"], updates)
                await session.commit()
                log.info(
                    "subtype set from SAP routing",
                    document_id=document_id,
                    subtype=routing["invoice_subtype"],
                    elapsed_ms=routing.get("elapsed_ms"),
                )

    return {"identity": identity, "routing": routing}


async def _ocr_track(document_id: str) -> None:
    """The existing extraction path, unchanged."""
    from src.workers.ocr_worker import run_extraction_direct

    await run_extraction_direct(document_id)


async def _apply_routing(document_id: str) -> dict[str, Any] | None:
    """Reconcile once both tracks are done: set the subtype and evaluate auto-post.

    Routing only overwrites the user's choice when
    PIPELINE_ROUTING_AUTHORITATIVE is on. Until then it records what it would
    have chosen, so its accuracy can be measured against real human decisions
    before it is given control.
    """
    from src.database import AsyncSessionLocal
    from src.repositories.document_repository import DocumentRepository
    from src.services.autopost_service import evaluate

    async with AsyncSessionLocal() as session:
        repo = DocumentRepository(session)
        doc = await repo.find_by_document_id(document_id)
        if not doc:
            return None

        pipeline = dict(doc.get("pipeline") or {})
        routing = pipeline.get("routing") or {}
        updates: dict[str, Any] = {}

        suggested = routing.get("invoice_subtype") or ""
        current = doc.get("invoice_subtype") or ""
        pipeline["subtype_suggested"] = suggested

        # Normally already applied by the fast track; this covers the case where
        # routing finished after OCR (a slow or briefly unavailable SAP).
        if suggested and settings.PIPELINE_ROUTING_AUTHORITATIVE and suggested != current:
            updates["invoice_subtype"] = suggested
            if routing.get("tcode"):
                updates["tcode"] = routing["tcode"]
            log.info("subtype applied at reconcile",
                     document_id=document_id, was=current or "-", now=suggested)

        # Auto-post evaluation reads the merged view of both tracks.
        merged = {**doc, "pipeline": pipeline, **updates}
        decision = await evaluate(merged)
        pipeline["autopost"] = decision
        pipeline["completed_at"] = datetime.now(UTC).isoformat()

        updates["pipeline"] = pipeline
        await repo.update(doc["id"], updates)
        await session.commit()

    return decision


async def run_pipeline(document_id: str) -> None:
    """Entry point — start both tracks, then reconcile.

    Never raises: a pipeline failure must not lose the document. If the fast
    track fails the document simply falls back to the existing manual flow.
    """
    bound_log = log.bind(document_id=document_id)
    started = datetime.now(UTC)

    if not settings.PIPELINE_ENABLED:
        await _ocr_track(document_id)
        return

    from src.database import AsyncSessionLocal
    from src.repositories.document_repository import DocumentRepository
    from src.services.storage_service import download_file

    async with AsyncSessionLocal() as session:
        doc = await DocumentRepository(session).find_by_document_id(document_id)
    if not doc:
        bound_log.error("document not found — pipeline aborted")
        return

    s3_key: str = (doc.get("file") or {}).get("s3_key", "")

    try:
        file_bytes = await download_file(s3_key)
    except Exception as exc:
        bound_log.error("could not read file — running OCR only", error=str(exc))
        await _ocr_track(document_id)
        return

    await _persist(document_id, {"started_at": started.isoformat()})

    # Both tracks run concurrently; neither can abort the other.
    fast_result, ocr_error = None, None
    async def _fast() -> None:
        nonlocal fast_result
        try:
            fast_result = await _fast_track(document_id, file_bytes, doc.get("tenant_id"))
        except Exception as exc:
            bound_log.error("fast track failed", error=str(exc))
            await _persist(document_id, {"fast_track_error": str(exc)})

    async def _ocr() -> None:
        nonlocal ocr_error
        try:
            await _ocr_track(document_id)
        except Exception as exc:
            ocr_error = exc
            bound_log.error("OCR track failed", error=str(exc))

    await asyncio.gather(_fast(), _ocr())

    if ocr_error is not None:
        return  # run_extraction_direct already recorded the failure

    # run_extraction_direct records its own failures without re-raising, so a
    # missing `extracted` is the reliable signal that OCR did not produce data.
    # Gating on it matters: without extracted fields every value-based check
    # would evaluate against zero and report misleading failures on a document
    # that simply never got read.
    async with AsyncSessionLocal() as session:
        current = await DocumentRepository(session).find_by_document_id(document_id)
    if not (current and current.get("extracted")):
        await _persist(document_id, {
            "skipped_reason": "Extraction produced no data — routing kept, checks not run.",
            "completed_at": datetime.now(UTC).isoformat(),
        })
        bound_log.warning("extraction produced no data — skipping auto-post evaluation")
        return

    decision = await _apply_routing(document_id)

    bound_log.info(
        "pipeline complete",
        route=(fast_result or {}).get("routing", {}).get("route"),
        identity_ms=(fast_result or {}).get("identity", {}).get("elapsed_ms"),
        routing_ms=(fast_result or {}).get("routing", {}).get("elapsed_ms"),
        total_ms=round((datetime.now(UTC) - started).total_seconds() * 1000),
        decision=(decision or {}).get("decision"),
    )

    # ── Act on the decision ────────────────────────────────────────────────
    # Only when every gate passed AND the operator has enabled it. The gate
    # evaluation is the authority here: this branch adds no judgement of its
    # own, it just stops waiting for a human. Any failure inside the chain
    # leaves the document exactly where a blocked manual attempt would.
    if (decision or {}).get("auto_post") and settings.AUTO_POST_ENABLED:
        from src.workers.process_worker import ProcessBlocked, run_process_direct

        bound_log.info("auto-posting — all gates passed")
        try:
            result = await run_process_direct(document_id, posted_by="auto-post")
            bound_log.info(
                "auto-post finished",
                posted=result.get("posted"),
                miro_number=result.get("miro_number"),
                grn_number=result.get("grn_number"),
            )
        except ProcessBlocked as exc:
            # Something the gates could not see — hand it back to a human with
            # the reason rather than retrying, since the chain may have posted
            # a goods receipt before stopping.
            bound_log.warning("auto-post blocked", reason=exc.reason, detail=exc.detail)
            await _persist(document_id, {"autopost_blocked": exc.reason})
        except Exception as exc:
            bound_log.error("auto-post failed", error=str(exc))
            await _persist(document_id, {"autopost_blocked": str(exc)})

    # Tell the sender what happened. Emailing an invoice and hearing nothing is
    # what makes people phone Accounts Payable, which is the cost this was meant
    # to remove. Never allowed to affect the document.
    try:
        from src.services.mail_reply import send_outcome
        await send_outcome(document_id)
    except Exception as exc:
        bound_log.warning("outcome reply failed", error=str(exc))
