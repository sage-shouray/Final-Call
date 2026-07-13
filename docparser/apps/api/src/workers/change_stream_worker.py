"""No-op replacement for the MongoDB change stream worker.

With PostgreSQL, real-time events are published directly by the Celery tasks
via Redis Streams.  This module is kept so main.py import paths stay unchanged.
"""
import asyncio

import structlog

log = structlog.get_logger(__name__)


async def start_change_stream_worker() -> None:
    """No-op: suspends indefinitely until cancelled on shutdown."""
    log.info("Change stream worker disabled (PostgreSQL mode)")
    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        pass
