"""Generic async repository providing CRUD primitives over a Motor collection."""
from datetime import UTC, datetime
from typing import Any

import structlog
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase
from pymongo import ReturnDocument

log = structlog.get_logger(__name__)

# Canonical sort direction type accepted by Motor
SortSpec = list[tuple[str, int]] | None


class BaseRepository:
    """Thin async wrapper around a single MongoDB collection.

    Keeps all raw Motor calls in one place; higher-level repositories
    extend this class and compose these primitives.
    """

    def __init__(self, collection_name: str, db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
        self._col: AsyncIOMotorCollection = db[collection_name]  # type: ignore[type-arg]
        self._name = collection_name

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    async def create(self, document: dict[str, Any]) -> str:
        """Insert a document and return its inserted _id as a hex string."""
        # Guarantee timestamps on every insert path
        now = datetime.now(UTC)
        document.setdefault("created_at", now)
        document.setdefault("updated_at", now)
        result = await self._col.insert_one(document)
        inserted_id = str(result.inserted_id)
        log.debug("document created", collection=self._name, id=inserted_id)
        return inserted_id

    async def update(
        self,
        id: str,
        update_data: dict[str, Any],
        *,
        upsert: bool = False,
    ) -> bool:
        """Patch a document by _id using $set.  Returns True when matched."""
        update_data["updated_at"] = datetime.now(UTC)
        result = await self._col.update_one(
            {"_id": ObjectId(id)},
            {"$set": update_data},
            upsert=upsert,
        )
        return result.matched_count > 0

    async def delete(self, id: str) -> bool:
        """Hard-delete a document by _id.  Returns True when deleted."""
        result = await self._col.delete_one({"_id": ObjectId(id)})
        return result.deleted_count > 0

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    async def find_by_id(self, id: str) -> dict[str, Any] | None:
        if not ObjectId.is_valid(id):
            return None
        return await self._col.find_one({"_id": ObjectId(id)})

    async def list(
        self,
        filter: dict[str, Any] | None = None,
        *,
        skip: int = 0,
        limit: int = 50,
        sort: SortSpec = None,
    ) -> list[dict[str, Any]]:
        query = filter or {}
        cursor = self._col.find(query).skip(skip).limit(limit)
        if sort:
            cursor = cursor.sort(sort)
        return await cursor.to_list(length=limit)

    async def count(self, filter: dict[str, Any] | None = None) -> int:
        query = filter or {}
        return await self._col.count_documents(query)

    async def find_one(self, filter: dict[str, Any]) -> dict[str, Any] | None:
        return await self._col.find_one(filter)

    async def find_one_and_update(
        self,
        filter: dict[str, Any],
        update: dict[str, Any],
        *,
        return_after: bool = True,
        upsert: bool = False,
    ) -> dict[str, Any] | None:
        return await self._col.find_one_and_update(
            filter,
            update,
            return_document=ReturnDocument.AFTER if return_after else ReturnDocument.BEFORE,
            upsert=upsert,
        )
