"""WebSocket endpoint for real-time document status updates."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.repositories.document_repository import DocumentRepository
from src.services.auth_service import auth_service
from src.services.event_service import connection_manager
from src.utils.serializer import serialize_doc

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/ws", tags=["WebSocket"])

_PING_INTERVAL = 30


async def _ping_loop(websocket: WebSocket) -> None:
    while True:
        await asyncio.sleep(_PING_INTERVAL)
        try:
            await websocket.send_json({"event": "PING", "timestamp": datetime.now(UTC).isoformat()})
        except Exception:
            break


@router.websocket("/{document_id}")
async def websocket_endpoint(websocket: WebSocket, document_id: str) -> None:
    await websocket.accept()

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

    from src.database import AsyncSessionLocal
    async with AsyncSessionLocal() as session:
        doc = await DocumentRepository(session).find_by_document_id(document_id)

    if not doc:
        await websocket.send_json({"event": "ERROR", "message": f"Document '{document_id}' not found"})
        await websocket.close(code=4004)
        return

    if payload.role == "operator" and doc.get("uploaded_by") != payload.sub:
        await websocket.send_json({"event": "ERROR", "message": "Forbidden"})
        await websocket.close(code=4003)
        return

    await connection_manager.connect(websocket, document_id)
    log.info("WebSocket established", document_id=document_id, user=payload.sub)

    safe = serialize_doc(doc)
    await websocket.send_json({
        "event":       "INITIAL_STATE",
        "document_id": document_id,
        "status":      safe.get("status"),
        "timestamp":   datetime.now(UTC).isoformat(),
        "data":        safe,
    })

    ping_task = asyncio.create_task(_ping_loop(websocket))
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        log.info("WebSocket disconnected", document_id=document_id, user=payload.sub)
    except Exception as exc:
        log.warning("WebSocket error", document_id=document_id, error=str(exc))
    finally:
        ping_task.cancel()
        await connection_manager.disconnect(websocket, document_id)
