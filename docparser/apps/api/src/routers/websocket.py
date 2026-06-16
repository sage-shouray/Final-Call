"""WebSocket endpoint for real-time document status updates.

GET /api/ws/{document_id}?token=<access_token>

Authentication
──────────────
Standard HTTP middleware cannot validate WebSocket connections because the
browser WebSocket API cannot send custom headers.  Instead, clients pass the
JWT as a query parameter:

    ws://host/api/ws/DOC-2026-123456?token=<access_token>

The /api/ws prefix is whitelisted in AuthMiddleware and RateLimitMiddleware so
this endpoint handles auth itself.

Connection lifecycle
────────────────────
1.  Accept the WebSocket upgrade.
2.  Validate the token from ?token= query param.
3.  Verify the user has access to the requested document.
4.  Send the current document state immediately ("INITIAL_STATE" event).
5.  Register in ConnectionManager so the event consumer can push updates.
6.  Keep alive with a PING every 30 s.
7.  On disconnect, remove from ConnectionManager.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.database import get_database
from src.repositories.document_repository import DocumentRepository
from src.services.auth_service import auth_service
from src.services.event_service import connection_manager
from src.utils.serializer import serialize_doc

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/ws", tags=["WebSocket"])

_PING_INTERVAL = 30  # seconds


# ---------------------------------------------------------------------------
# Ping loop
# ---------------------------------------------------------------------------


async def _ping_loop(websocket: WebSocket) -> None:
    """Send a heartbeat every 30 s so proxies don't close idle connections."""
    while True:
        await asyncio.sleep(_PING_INTERVAL)
        try:
            await websocket.send_json(
                {"event": "PING", "timestamp": datetime.now(UTC).isoformat()}
            )
        except Exception:
            break


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------


@router.websocket("/{document_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    document_id: str,
) -> None:
    """Stream real-time status events for a single document."""
    # ── 1. Accept upgrade ──────────────────────────────────────────────────
    await websocket.accept()

    # ── 2. Validate JWT from query param ──────────────────────────────────
    token = websocket.query_params.get("token", "")
    if not token:
        await websocket.send_json({"event": "ERROR", "message": "Missing token"})
        await websocket.close(code=4001)
        return

    try:
        payload = await auth_service.verify_token(token)
        if await auth_service.is_blacklisted(payload.jti):
            await websocket.send_json({"event": "ERROR", "message": "Token revoked"})
            await websocket.close(code=4001)
            return
    except Exception:
        await websocket.send_json({"event": "ERROR", "message": "Invalid token"})
        await websocket.close(code=4001)
        return

    # ── 3. Verify document access ──────────────────────────────────────────
    db = get_database()
    doc = await DocumentRepository(db).find_by_document_id(document_id)
    if not doc:
        await websocket.send_json(
            {"event": "ERROR", "message": f"Document '{document_id}' not found"}
        )
        await websocket.close(code=4004)
        return

    # Operators can only watch their own documents; managers/admins see all
    if payload.role == "operator" and doc.get("uploaded_by") != payload.sub:
        await websocket.send_json({"event": "ERROR", "message": "Forbidden"})
        await websocket.close(code=4003)
        return

    # ── 4. Register and send initial state ────────────────────────────────
    await connection_manager.connect(websocket, document_id)
    log.info(
        "WebSocket established",
        document_id=document_id,
        user=payload.sub,
        role=payload.role,
    )

    safe = serialize_doc(doc)
    await websocket.send_json(
        {
            "event": "INITIAL_STATE",
            "document_id": document_id,
            "status": safe.get("status"),
            "timestamp": datetime.now(UTC).isoformat(),
            "data": safe,
        }
    )

    # ── 5. Start ping task and wait for disconnect ─────────────────────────
    ping_task = asyncio.create_task(_ping_loop(websocket))
    try:
        while True:
            # receive_text() yields for client-sent pings/pongs; raises on disconnect
            await websocket.receive_text()
    except WebSocketDisconnect:
        log.info("WebSocket disconnected", document_id=document_id, user=payload.sub)
    except Exception as exc:
        log.warning("WebSocket error", document_id=document_id, error=str(exc))
    finally:
        ping_task.cancel()
        await connection_manager.disconnect(websocket, document_id)
