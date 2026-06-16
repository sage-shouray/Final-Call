"""MongoDB Change Streams → Redis Stream bridge.

Watches the ``documents`` collection for any document where the ``status``
field changes, or for newly inserted documents.  On each event it publishes
a STATUS_CHANGED event to ``documents:lifecycle`` so the event consumer can
push the update to connected WebSocket clients.

This acts as a reliable backup to the events published by the Celery tasks:
even if a task forgets to call ``redis.xadd``, the change stream catches the
MongoDB write and fills the gap.

Resume token
────────────
The change stream position is stored in Redis under ``change_stream:resume_token``
so the worker can resume from where it left off after a restart.  If the token
is invalid (e.g. the oplog rolled over) the worker restarts from the current
tail and logs a warning.

Retry / back-off
────────────────
On any unexpected error the worker waits with exponential back-off (1 s → 30 s)
before reconnecting.  On CancelledError it exits cleanly.
"""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

import structlog

from src.services.event_service import STREAM_LIFECYCLE, publish

log = structlog.get_logger(__name__)

_RESUME_TOKEN_KEY = "change_stream:resume_token"

# Only fire on status changes (updates) and new document inserts
_PIPELINE: list[dict[str, Any]] = [
    {
        "$match": {
            "$or": [
                {"operationType": "insert"},
                {
                    "operationType": {"$in": ["update", "replace"]},
                    "updateDescription.updatedFields.status": {"$exists": True},
                },
            ]
        }
    }
]


# ---------------------------------------------------------------------------
# Change processing
# ---------------------------------------------------------------------------


async def _process_change(change: dict[str, Any]) -> None:
    op = change.get("operationType", "")

    if op == "insert":
        full_doc = change.get("fullDocument") or {}
        document_id = full_doc.get("document_id") or ""
        status = full_doc.get("status") or "uploaded"
    else:
        # For updates, fullDocument is populated via fullDocument="updateLookup"
        full_doc = change.get("fullDocument") or {}
        updated_fields = change.get("updateDescription", {}).get("updatedFields", {})
        document_id = full_doc.get("document_id") or ""
        status = updated_fields.get("status") or full_doc.get("status") or ""

    if not document_id or not status:
        return

    await publish(
        STREAM_LIFECYCLE,
        "STATUS_CHANGED",
        {
            "document_id": document_id,
            "status": status,
            "source": "change_stream",
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )

    log.debug(
        "change stream event published",
        document_id=document_id,
        status=status,
        op=op,
    )


# ---------------------------------------------------------------------------
# Watch loop
# ---------------------------------------------------------------------------


async def _watch_loop() -> None:
    from src.database import get_database
    from src.utils.redis_client import get_redis

    redis = get_redis()
    db = get_database()
    retry_delay = 1.0

    while True:
        # Load resume token from Redis
        resume_token: dict[str, Any] | None = None
        try:
            token_json = await redis.get(_RESUME_TOKEN_KEY)
            if token_json:
                resume_token = json.loads(token_json)
        except Exception:
            pass

        watch_kwargs: dict[str, Any] = {"full_document": "updateLookup"}
        if resume_token:
            watch_kwargs["resume_after"] = resume_token

        try:
            async with db["documents"].watch(_PIPELINE, **watch_kwargs) as stream:
                retry_delay = 1.0  # reset on successful connection
                log.info(
                    "Change stream watching documents collection",
                    resuming=resume_token is not None,
                )

                async for change in stream:
                    try:
                        await _process_change(change)
                    except Exception as exc:
                        log.error("Change event processing error", error=str(exc))

                    # Persist resume token after each processed event
                    try:
                        rt = stream.resume_token
                        if rt:
                            await redis.set(_RESUME_TOKEN_KEY, json.dumps(rt))
                    except Exception:
                        pass

        except asyncio.CancelledError:
            log.info("Change stream worker shutting down")
            raise

        except Exception as exc:
            err_str = str(exc)
            log.error("Change stream error — will retry", error=err_str, delay=retry_delay)

            # Stale resume token — clear it so next attempt starts from tail
            if any(k in err_str for k in ("resume", "ChangeStreamHistoryLost", "invalidated")):
                log.warning("Stale resume token cleared")
                resume_token = None
                try:
                    await redis.delete(_RESUME_TOKEN_KEY)
                except Exception:
                    pass

            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 30.0)


# ---------------------------------------------------------------------------
# Public entry-point (called from lifespan)
# ---------------------------------------------------------------------------


async def start_change_stream_worker() -> None:
    """Entry-point for asyncio.create_task().  Swallows CancelledError on shutdown."""
    try:
        await _watch_loop()
    except asyncio.CancelledError:
        pass
