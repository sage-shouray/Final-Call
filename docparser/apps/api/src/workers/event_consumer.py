"""Background asyncio task: Redis Stream consumer → WebSocket broadcaster.

Reads from the ``documents:lifecycle`` stream using a consumer group so that:
  * Multiple webapp replicas share the work (one replica processes each message).
  * Messages are re-delivered if a replica crashes before ACKing.

On startup the consumer:
  1. Creates the consumer group if it doesn't exist (idempotent BUSYGROUP check).
  2. Processes any pending / un-ACKed messages from previous runs (id="0").
  3. Switches to ``">"`` to read new messages with a 5-second block timeout.

For each event the consumer:
  - Parses the payload.
  - Enriches it with a human-readable step/label.
  - Broadcasts to all WebSocket connections watching that document_id.
  - Invalidates the dashboard metrics cache so the next GET /metrics is fresh.

Event types mapped
──────────────────
  STATUS_CHANGED       — any status transition (caught from change stream)
  OCR_COMPLETE         — extraction finished successfully
  VALIDATION_COMPLETE  — SAP validation finished
  MIRO_POSTED          — successfully posted to SAP
  ERROR                — any stage failure
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime
from typing import Any

import structlog

from src.services.event_service import CONSUMER_GROUP, STREAM_LIFECYCLE, connection_manager

log = structlog.get_logger(__name__)

# Human-readable step metadata per document status
_STATUS_META: dict[str, dict[str, Any]] = {
    "uploaded":   {"step": 1, "label": "Document uploaded"},
    "extracting": {"step": 2, "label": "AI extraction in progress"},
    "extracted":  {"step": 3, "label": "AI extraction complete"},
    "validating": {"step": 4, "label": "SAP validation in progress"},
    "validated":  {"step": 5, "label": "SAP validation complete"},
    "posting":    {"step": 6, "label": "Posting to SAP MIRO"},
    "posted":     {"step": 7, "label": "Posted to SAP successfully"},
    "failed":     {"step": -1, "label": "Processing failed"},
}

_DASHBOARD_CACHE_KEY = "cache:dashboard:metrics"
_INVALIDATE_ON = {"STATUS_CHANGED", "OCR_COMPLETE", "VALIDATION_COMPLETE", "MIRO_POSTED", "ERROR"}


# ---------------------------------------------------------------------------
# Event processing
# ---------------------------------------------------------------------------


async def _invalidate_dashboard_cache(redis: Any) -> None:
    try:
        await redis.delete(_DASHBOARD_CACHE_KEY)
    except Exception:
        pass


async def _process_event(msg_data: dict[str, Any], redis: Any) -> None:
    event_type = msg_data.get("event_type") or "STATUS_CHANGED"
    document_id = msg_data.get("document_id") or ""
    timestamp = msg_data.get("timestamp") or datetime.now(UTC).isoformat()

    try:
        payload: dict[str, Any] = json.loads(msg_data.get("payload") or "{}")
    except Exception:
        payload = {}

    status = payload.get("status") or ""
    meta = _STATUS_META.get(status, {"step": 0, "label": status or event_type})

    # Build the message that WebSocket clients receive
    extra = {k: v for k, v in payload.items() if k not in {"status", "document_id", "source"}}
    ws_message: dict[str, Any] = {
        "event": event_type,
        "document_id": document_id,
        "status": status,
        "timestamp": timestamp,
        "data": {
            "step": meta["step"],
            "label": meta["label"],
            **extra,
        },
    }

    if document_id:
        await connection_manager.broadcast_to_document(document_id, ws_message)

    if event_type in _INVALIDATE_ON:
        await _invalidate_dashboard_cache(redis)


# ---------------------------------------------------------------------------
# Consumer loop
# ---------------------------------------------------------------------------


async def _consume_pending(redis: Any, consumer_name: str) -> None:
    """Process any messages that were delivered but never ACKed (from a crash)."""
    while True:
        messages = await redis.xreadgroup(
            groupname=CONSUMER_GROUP,
            consumername=consumer_name,
            streams={STREAM_LIFECYCLE: "0"},
            count=50,
        )
        if not messages:
            break
        for _stream, stream_messages in messages:
            for msg_id, msg_data in stream_messages:
                if not msg_data:  # empty — already ACKed by another consumer
                    continue
                await _process_event(msg_data, redis)
                await redis.xack(STREAM_LIFECYCLE, CONSUMER_GROUP, msg_id)
        if len(messages[0][1]) < 50:
            break  # no more pending


async def _streams_supported(redis: Any) -> bool:
    """Return False if this Redis version doesn't support Streams (< 5.0)."""
    try:
        await redis.xgroup_create("__probe__", "__probe__", id="0", mkstream=True)
        await redis.delete("__probe__")
        return True
    except Exception as exc:
        if "unknown command" in str(exc).lower():
            return False
        # BUSYGROUP means the stream exists — Streams ARE supported
        return True


async def _consume_loop() -> None:
    """Main consumer loop — runs until the asyncio task is cancelled."""
    from src.utils.redis_client import get_redis

    redis = get_redis()
    consumer_name = f"webapp-{os.getpid()}"

    # Check if Redis Streams are supported before starting
    if not await _streams_supported(redis):
        log.warning(
            "Redis Streams not supported (Redis < 5.0) — event consumer disabled. "
            "WebSocket live updates will not work. Upgrade Redis to 5.0+ to enable."
        )
        # Park the task so it can still be cancelled cleanly on shutdown
        while True:
            await asyncio.sleep(60)

    # Ensure the consumer group exists (BUSYGROUP = already exists → fine)
    try:
        await redis.xgroup_create(
            STREAM_LIFECYCLE, CONSUMER_GROUP, id="0", mkstream=True
        )
        log.info("Consumer group created", group=CONSUMER_GROUP, stream=STREAM_LIFECYCLE)
    except Exception as exc:
        if "BUSYGROUP" not in str(exc):
            log.warning("xgroup_create error", error=str(exc))

    # Drain pending messages first
    try:
        await _consume_pending(redis, consumer_name)
    except Exception as exc:
        log.warning("Pending message drain error", error=str(exc))

    log.info("Event consumer started", consumer=consumer_name)

    while True:
        try:
            messages = await redis.xreadgroup(
                groupname=CONSUMER_GROUP,
                consumername=consumer_name,
                streams={STREAM_LIFECYCLE: ">"},
                count=10,
                block=5_000,  # 5-second timeout so the loop can be cancelled
            )

            if not messages:
                continue

            for _stream, stream_messages in messages:
                for msg_id, msg_data in stream_messages:
                    try:
                        await _process_event(msg_data, redis)
                    except Exception as exc:
                        log.error(
                            "Event processing error",
                            msg_id=msg_id,
                            error=str(exc),
                        )
                    finally:
                        await redis.xack(STREAM_LIFECYCLE, CONSUMER_GROUP, msg_id)

        except asyncio.CancelledError:
            log.info("Event consumer shutting down", consumer=consumer_name)
            break
        except Exception as exc:
            log.error("Event consumer loop error", error=str(exc))
            await asyncio.sleep(2)


# ---------------------------------------------------------------------------
# Public entry-point (called from lifespan)
# ---------------------------------------------------------------------------


async def start_event_consumer() -> None:
    """Entry-point for asyncio.create_task().  Swallows CancelledError on shutdown."""
    try:
        await _consume_loop()
    except asyncio.CancelledError:
        pass
