"""DocumentRepository — all database operations for the documents collection."""
from datetime import UTC, datetime
from typing import Any

import structlog
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import DESCENDING

from src.models.document import DocumentStatus
from src.repositories.base import BaseRepository

log = structlog.get_logger(__name__)

_COLLECTION = "documents"


class DocumentRepository(BaseRepository):
    def __init__(self, db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
        super().__init__(_COLLECTION, db)

    # ------------------------------------------------------------------
    # Lookups
    # ------------------------------------------------------------------

    async def find_by_document_id(self, document_id: str) -> dict[str, Any] | None:
        """Find a document by its human-readable ID (e.g. DOC-2026-4412)."""
        return await self.find_one({"document_id": document_id})

    async def find_by_po_number(self, po_number: str) -> list[dict[str, Any]]:
        """Return all documents whose extracted PO number matches."""
        return await self.list({"extracted.po_number": po_number})

    async def get_recent_documents(self, limit: int = 20) -> list[dict[str, Any]]:
        return await self.list(
            sort=[("uploaded_at", DESCENDING)],
            limit=limit,
        )

    # ------------------------------------------------------------------
    # Status & retry management
    # ------------------------------------------------------------------

    async def update_status(
        self,
        id: str,
        status: DocumentStatus,
        *,
        error_entry: dict[str, Any] | None = None,
    ) -> bool:
        """Atomically set status and, if an error occurred, append to error_log."""
        payload: dict[str, Any] = {"status": status.value}

        if error_entry:
            error_entry.setdefault("timestamp", datetime.now(UTC))
            result = await self.find_one_and_update(
                {"_id": ObjectId(id)},
                {
                    "$set": {**payload, "updated_at": datetime.now(UTC)},
                    "$push": {"error_log": error_entry},
                },
            )
            return result is not None

        return await self.update(id, payload)

    async def increment_retry(self, id: str) -> int:
        """Atomically increment retry_count; returns the new value."""
        doc = await self.find_one_and_update(
            {"_id": ObjectId(id)},
            {
                "$inc": {"retry_count": 1},
                "$set": {"updated_at": datetime.now(UTC)},
            },
        )
        return int(doc["retry_count"]) if doc else 0

    # ------------------------------------------------------------------
    # Extracted data / SAP / MIRO updates
    # ------------------------------------------------------------------

    async def update_extracted_data(
        self, id: str, extracted_data: dict[str, Any]
    ) -> bool:
        return await self.update(
            id,
            {
                "extracted": extracted_data,
                "status": DocumentStatus.EXTRACTED.value,
            },
        )

    async def update_sap_validation(
        self, id: str, validation_data: dict[str, Any]
    ) -> bool:
        return await self.update(
            id,
            {
                "sap_validation": validation_data,
                "status": DocumentStatus.VALIDATED.value,
            },
        )

    async def update_miro_posting(
        self, id: str, posting_data: dict[str, Any]
    ) -> bool:
        new_status = (
            DocumentStatus.POSTED
            if posting_data.get("status") == "success"
            else DocumentStatus.VALIDATED  # keep validated so user can retry MIRO
        )
        return await self.update(
            id,
            {
                "miro_posting": posting_data,
                "status": new_status.value,
            },
        )

    # ------------------------------------------------------------------
    # Aggregations
    # ------------------------------------------------------------------

    async def list_documents(
        self,
        *,
        filter_query: dict[str, Any] | None = None,
        skip: int = 0,
        limit: int = 20,
        sort: list[tuple[str, int]] | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """Return (documents, total_count) with a lightweight projection for the list view."""
        fq = filter_query or {}
        srt = sort or [("uploaded_at", DESCENDING)]
        projection: dict[str, int] = {
            "_id": 1,
            "document_id": 1,
            "type": 1,
            "tcode": 1,
            "status": 1,
            "uploaded_at": 1,
            "extracted.vendor_name": 1,
            "extracted.gross_amount": 1,
            "miro_posting.miro_number": 1,
        }
        cursor = self._col.find(fq, projection).sort(srt).skip(skip).limit(limit)
        docs = await cursor.to_list(length=limit)
        total = await self._col.count_documents(fq)
        return docs, total

    async def get_dashboard_metrics(self) -> dict[str, Any]:
        """Return counts by status, counts by tcode, and total gross_amount."""
        pipeline: list[dict[str, Any]] = [
            {
                "$facet": {
                    "by_status": [
                        {"$group": {"_id": "$status", "count": {"$sum": 1}}},
                        {"$sort": {"_id": 1}},
                    ],
                    "by_tcode": [
                        {"$group": {"_id": "$tcode", "count": {"$sum": 1}}},
                        {"$sort": {"_id": 1}},
                    ],
                    "total_value": [
                        {
                            "$group": {
                                "_id": None,
                                "total": {
                                    "$sum": {
                                        "$toDecimal": {
                                            "$ifNull": ["$extracted.gross_amount", "0"]
                                        }
                                    }
                                },
                                "total_documents": {"$sum": 1},
                            }
                        }
                    ],
                    "by_type": [
                        {"$group": {"_id": "$type", "count": {"$sum": 1}}},
                        {"$sort": {"_id": 1}},
                    ],
                    "recent_trend": [
                        {
                            "$group": {
                                "_id": {
                                    "$dateToString": {
                                        "format": "%Y-%m-%d",
                                        "date": "$uploaded_at",
                                    }
                                },
                                "count": {"$sum": 1},
                            }
                        },
                        {"$sort": {"_id": -1}},
                        {"$limit": 30},
                    ],
                }
            }
        ]
        results = await self._col.aggregate(pipeline).to_list(length=1)
        raw = results[0] if results else {}

        # Normalise into a flat, frontend-friendly dict
        by_status = {item["_id"]: item["count"] for item in raw.get("by_status", [])}
        by_tcode = {item["_id"]: item["count"] for item in raw.get("by_tcode", [])}
        by_type = {item["_id"]: item["count"] for item in raw.get("by_type", [])}
        value_row = raw["total_value"][0] if raw.get("total_value") else {}

        return {
            "by_status": by_status,
            "by_tcode": by_tcode,
            "by_type": by_type,
            "total_documents": value_row.get("total_documents", 0),
            "total_value": round(float(str(value_row.get("total", 0) or 0)), 2),
            "recent_trend": raw.get("recent_trend", []),
        }
