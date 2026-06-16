"""Real-time event backbone: Redis Streams publisher + WebSocket ConnectionManager.

ConnectionManager
─────────────────
Module-level singleton.  asyncio is single-threaded so plain dict operations
are safe without locks.  Iterating over a copy (``list(...)``) protects against
mutation during send.

Streams
───────
  documents:lifecycle — all document state changes (STATUS_CHANGED, OCR_COMPLETE …)
  documents:errors    — failures and exceptions

publish()
─────────
Fire-and-forget helper used by every component that emits events.  Failures are
logged and swallowed so a Redis outage never breaks the main request path.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import WebSocket

log = structlog.get_logger(__name__)

# Public stream names — import these instead of duplicating the strings
STREAM_LIFECYCLE = "documents:lifecycle"
STREAM_ERRORS = "documents:errors"

# Consumer group shared by all workers reading lifecycle events
CONSUMER_GROUP = "docparser_workers"


# ---------------------------------------------------------------------------
# ConnectionManager
# ---------------------------------------------------------------------------


class ConnectionManager:
    """Manages active WebSocket connections keyed by document_id."""

    def __init__(self) -> None:
        self._connections: dict[str, list[WebSocket]] = {}

    @property
    def active_count(self) -> int:
        return sum(len(v) for v in self._connections.values())

    async def connect(self, websocket: WebSocket, document_id: str) -> None:
        self._connections.setdefault(document_id, []).append(websocket)
        log.debug(
            "WebSocket connected",
            document_id=document_id,
            total=self.active_count,
        )

    async def disconnect(self, websocket: WebSocket, document_id: str) -> None:
        conns = self._connections.get(document_id, [])
        if websocket in conns:
            conns.remove(websocket)
        if not conns:
            self._connections.pop(document_id, None)
        log.debug(
            "WebSocket disconnected",
            document_id=document_id,
            total=self.active_count,
        )

    async def broadcast_to_document(
        self, document_id: str, message: dict[str, Any]
    ) -> None:
        """Send message to all sockets watching this document.  Dead sockets are pruned."""
        connections = list(self._connections.get(document_id, []))
        dead: list[WebSocket] = []
        for ws in connections:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            await self.disconnect(ws, document_id)

    async def broadcast_to_all(self, message: dict[str, Any]) -> None:
        for doc_id in list(self._connections):
            await self.broadcast_to_document(doc_id, message)


# Module-level singleton — import ``connection_manager`` everywhere
connection_manager = ConnectionManager()


# ---------------------------------------------------------------------------
# Redis Streams publisher
# ---------------------------------------------------------------------------


async def publish(
    stream: str,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    """Publish an event to a Redis Stream.

    Fields stored per message:
        event_type   — e.g. "STATUS_CHANGED"
        document_id  — extracted from payload for easy consumer filtering
        timestamp    — ISO 8601 UTC
        payload      — JSON-encoded full event data
    """
    try:
        from src.utils.redis_client import get_redis
        redis = get_redis()
        await redis.xadd(
            stream,
            {
                "event_type": event_type,
                "document_id": payload.get("document_id", ""),
                "timestamp": datetime.now(UTC).isoformat(),
                "payload": json.dumps(payload, default=str),
            },
        )
    except Exception as exc:
        log.warning(
            "Redis Stream publish failed",
            stream=stream,
            event_type=event_type,
            error=str(exc),
        )
