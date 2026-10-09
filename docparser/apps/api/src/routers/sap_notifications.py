"""Inbound endpoint — SAP posts here when a PO's stock clears quality hold.

Replaces the earlier plan of SAP emailing the shared mailbox: their own code
now calls this directly. Authenticated by a shared API key rather than a
logged-in user, since the caller is SAP's system, not a person with an account
here. The request is only ever recorded, never acted on inline — see
sap_notification_worker.py for why.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import APIRouter, Header, HTTPException

from src.config import settings
from src.database import AsyncSessionLocal
from src.models.sap_notification import SapNotificationRow

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/sap/notifications", tags=["SAP Notifications"])


def _check_api_key(x_api_key: str | None) -> None:
    expected = settings.SAP_NOTIFICATION_API_KEY.get_secret_value()
    if not expected:
        # No key configured yet — the endpoint is reachable but unlocked.
        # Acceptable only while testing locally; a real key must be set
        # before this is exposed to the internet.
        log.warning("SAP notification accepted with no API key configured")
        return
    if x_api_key != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key.")


@router.post("", status_code=202)
async def receive_notification(
    body: dict[str, Any],
    x_api_key: str | None = Header(default=None),
) -> dict[str, Any]:
    """SAP posts {"po_number": "...", "status": "unblocked", "message": "..."}.

    Field names are a best-effort default (po_number/status/message); whatever
    SAP's team actually sends is still recorded in full via raw_payload, so a
    mismatch in field naming shows up in the data rather than silently
    dropping the request.
    """
    _check_api_key(x_api_key)

    po_number = str(body.get("po_number") or body.get("PO") or body.get("PO_NUMBER") or "").strip()
    if not po_number:
        raise HTTPException(status_code=422, detail="po_number is required.")

    row_id = str(uuid.uuid4())
    async with AsyncSessionLocal() as session:
        session.add(SapNotificationRow(
            id=row_id,
            po_number=po_number,
            status=str(body.get("status") or body.get("STATUS") or "").strip(),
            message=str(body.get("message") or body.get("MESSAGE") or "").strip(),
            raw_payload=body,
            received_at=datetime.now(UTC),
        ))
        await session.commit()

    log.info("SAP notification received", po_number=po_number, id=row_id)
    return {"received": True, "id": row_id}


@router.get("")
async def list_notifications(limit: int = 50) -> list[dict[str, Any]]:
    """Recent notifications, for visibility/debugging — not the scheduler's
    own read path, which queries the table directly."""
    from sqlalchemy import select

    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(SapNotificationRow).order_by(SapNotificationRow.received_at.desc()).limit(limit)
        )).scalars().all()
    return [r.to_dict() for r in rows]
