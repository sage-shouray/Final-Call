"""Scheduler — picks up SAP's stored stock-release notifications and acts on them.

One POST from SAP only records a row (sap_notifications.py); this is the half
that actually does something with it, on its own cadence, same shape as the
mail poller: cheap, frequent, and never lets a single bad row block the rest.

A matching document may not exist yet the first time a notification is seen —
GRN-103 and the notification can race in theory, even though the real sequence
(GR posted, then quality team releases it, then SAP notifies) makes it rare.
Rather than fail permanently, an unmatched notification is retried on later
ticks, up to a cap, so a few seconds of lag resolves itself instead of needing
a human to re-send anything.
"""
from __future__ import annotations

import asyncio

import structlog

log = structlog.get_logger(__name__)

_POLL_INTERVAL_S = 15
_MAX_ATTEMPTS = 20  # ~5 minutes of retrying at the interval above


async def _process_one(row_id: str) -> None:
    from sqlalchemy import select

    from src.database import AsyncSessionLocal
    from src.models.document import DocumentRow, DocumentStatus
    from src.models.sap_notification import SapNotificationRow

    async with AsyncSessionLocal() as session:
        notif = (await session.execute(
            select(SapNotificationRow).where(SapNotificationRow.id == row_id)
        )).scalar_one_or_none()
        if not notif or notif.processed:
            return

        bound = log.bind(notification_id=row_id, po_number=notif.po_number)

        doc = (await session.execute(
            select(DocumentRow).where(
                DocumentRow.extracted["po_number"].astext == notif.po_number,
                DocumentRow.status == DocumentStatus.GR_POSTED.value,
                DocumentRow.grn_posting["pending_quality_release"].astext == "true",
            ).order_by(DocumentRow.uploaded_at.desc()).limit(1)
        )).scalars().first()

        if not doc:
            notif.attempts += 1
            if notif.attempts >= _MAX_ATTEMPTS:
                notif.processed = True
                notif.result = "given up — no matching document found after repeated retries"
                bound.warning("notification abandoned — no matching document", attempts=notif.attempts)
            else:
                bound.info("no matching document yet — will retry", attempts=notif.attempts)
            await session.commit()
            return

        notif.processed = True
        notif.document_id = doc.document_id
        await session.commit()

    bound.info("matched document — auto-parking MIRO", document_id=doc.document_id)
    try:
        from src.workers.sap_worker import run_miro_park_direct
        await run_miro_park_direct(doc.document_id, posted_by="sap-notification")
    except Exception as exc:
        bound.error("auto-park from SAP notification failed", document_id=doc.document_id, error=str(exc))
        result = f"error: {exc}"
    else:
        # run_miro_park_direct never raises on a blocked or failed posting —
        # it logs and returns — so the only reliable way to know what actually
        # happened is to read the document back afterward, not assume success
        # just because no exception came out of the call.
        async with AsyncSessionLocal() as session:
            refreshed = (await session.execute(
                select(DocumentRow).where(DocumentRow.document_id == doc.document_id)
            )).scalars().first()
        parking = (refreshed.miro_parking or {}) if refreshed else {}
        if parking.get("status") == "success":
            result = f"parked as {parking.get('park_number') or '(no number returned)'}"
        elif refreshed and refreshed.status == DocumentStatus.FAILED.value:
            result = "blocked — invoice does not match SAP (see document error log)"
        else:
            result = parking.get("message") or "MIRO park did not succeed — see document for details"

    async with AsyncSessionLocal() as session:
        notif2 = (await session.execute(
            select(SapNotificationRow).where(SapNotificationRow.id == row_id)
        )).scalar_one_or_none()
        if notif2:
            notif2.result = result
            await session.commit()


async def process_pending_notifications() -> None:
    from sqlalchemy import select

    from src.database import AsyncSessionLocal
    from src.models.sap_notification import SapNotificationRow

    async with AsyncSessionLocal() as session:
        pending_ids = (await session.execute(
            select(SapNotificationRow.id).where(SapNotificationRow.processed.is_(False))
        )).scalars().all()

    for row_id in pending_ids:
        try:
            await _process_one(row_id)
        except Exception as exc:
            log.error("notification processing crashed", notification_id=row_id, error=str(exc))


async def start_sap_notification_worker() -> None:
    log.info("SAP notification worker started", poll_interval_s=_POLL_INTERVAL_S)
    try:
        while True:
            try:
                await process_pending_notifications()
            except Exception as exc:
                log.error("notification poll cycle failed", error=str(exc))
            await asyncio.sleep(_POLL_INTERVAL_S)
    except asyncio.CancelledError:
        log.info("SAP notification worker stopped")
