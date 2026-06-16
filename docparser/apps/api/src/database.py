"""Async MongoDB connection management via Motor."""
from collections.abc import AsyncGenerator

import structlog
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING, IndexModel

from src.config import settings

log = structlog.get_logger(__name__)

_client: AsyncIOMotorClient | None = None  # type: ignore[type-arg]

# ---------------------------------------------------------------------------
# Index definitions — declared here so startup can ensure_indexes atomically
# ---------------------------------------------------------------------------
_INDEX_SPECS: dict[str, list[IndexModel]] = {
    "documents": [
        IndexModel([("document_id", ASCENDING)], unique=True, name="document_id_unique"),
        IndexModel([("status", ASCENDING)], name="status"),
        IndexModel([("type", ASCENDING)], name="type"),
        IndexModel([("tcode", ASCENDING)], name="tcode"),
        IndexModel([("uploaded_at", DESCENDING)], name="uploaded_at_desc"),
        IndexModel([("uploaded_by", ASCENDING)], name="uploaded_by"),
        # Compound index for the common dashboard query pattern
        IndexModel(
            [("status", ASCENDING), ("uploaded_at", DESCENDING)],
            name="status_uploaded_at",
        ),
        IndexModel(
            [("extracted.po_number", ASCENDING)],
            name="po_number",
            sparse=True,
        ),
    ],
    "audit_logs": [
        IndexModel([("document_id", ASCENDING)], name="audit_document_id"),
        IndexModel([("timestamp", DESCENDING)], name="audit_timestamp_desc"),
        IndexModel(
            [("document_id", ASCENDING), ("timestamp", DESCENDING)],
            name="audit_document_timestamp",
        ),
    ],
    "users": [
        IndexModel([("email", ASCENDING)], unique=True, name="email_unique"),
        IndexModel([("role", ASCENDING)], name="role"),
    ],
}


async def connect_db() -> None:
    global _client
    _client = AsyncIOMotorClient(
        str(settings.MONGODB_URL),
        maxPoolSize=settings.MONGODB_MAX_POOL_SIZE,
        minPoolSize=settings.MONGODB_MIN_POOL_SIZE,
        connectTimeoutMS=settings.MONGODB_CONNECT_TIMEOUT_MS,
        serverSelectionTimeoutMS=settings.MONGODB_SERVER_SELECTION_TIMEOUT_MS,
        # Keeps the driver from retrying on non-transient errors forever
        retryWrites=True,
        retryReads=True,
    )
    # Verify the connection is reachable before declaring startup complete
    await _client.admin.command("ping")
    log.info(
        "MongoDB connected",
        db=settings.MONGODB_DB_NAME,
        max_pool=settings.MONGODB_MAX_POOL_SIZE,
        min_pool=settings.MONGODB_MIN_POOL_SIZE,
    )
    await _ensure_indexes()


async def _ensure_indexes() -> None:
    db = get_database()
    for collection_name, indexes in _INDEX_SPECS.items():
        collection = db[collection_name]
        await collection.create_indexes(indexes)
        log.debug("Indexes ensured", collection=collection_name, count=len(indexes))


async def close_db() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None
        log.info("MongoDB connection closed")


def get_database() -> AsyncIOMotorDatabase:  # type: ignore[type-arg]
    if _client is None:
        raise RuntimeError("Database not initialised — call connect_db() first")
    return _client[settings.MONGODB_DB_NAME]


async def get_db() -> AsyncGenerator[AsyncIOMotorDatabase, None]:  # type: ignore[type-arg]
    """FastAPI dependency — yields the database instance."""
    yield get_database()
