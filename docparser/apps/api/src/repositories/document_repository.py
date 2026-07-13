"""DocumentRepository — all database operations for the documents table."""
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import Numeric, asc, cast, desc, func, select, text, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.document import DocumentRow, DocumentStatus
from src.repositories.base import BaseRepository

log = structlog.get_logger(__name__)


class DocumentRepository(BaseRepository[DocumentRow]):
    _model = DocumentRow

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    # ------------------------------------------------------------------
    # Lookups
    # ------------------------------------------------------------------

    async def find_by_document_id(self, document_id: str) -> dict[str, Any] | None:
        return await self.find_one({"document_id": document_id})

    async def find_by_po_number(self, po_number: str) -> list[dict[str, Any]]:
        stmt = (
            select(DocumentRow)
            .where(DocumentRow.extracted["po_number"].as_string() == po_number)
        )
        result = await self._session.execute(stmt)
        return [row.to_dict() for row in result.scalars().all()]

    async def get_recent_documents(self, limit: int = 20) -> list[dict[str, Any]]:
        return await self.list(sort=[("uploaded_at", -1)], limit=limit)

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
        if error_entry:
            error_entry.setdefault("timestamp", datetime.now(UTC).isoformat())
            # Append to JSONB array using PostgreSQL || operator
            stmt = (
                update(DocumentRow)
                .where(DocumentRow.id == id)
                .values(
                    status=status.value,
                    error_log=func.coalesce(DocumentRow.error_log, cast([], JSONB)).op("||")(
                        cast([error_entry], JSONB)
                    ),
                    updated_at=datetime.now(UTC),
                )
                .returning(DocumentRow.id)
            )
            result = await self._session.execute(stmt)
            return result.scalar_one_or_none() is not None

        return await self.update(id, {"status": status.value})

    async def increment_retry(self, id: str) -> int:
        stmt = (
            update(DocumentRow)
            .where(DocumentRow.id == id)
            .values(
                retry_count=DocumentRow.retry_count + 1,
                updated_at=datetime.now(UTC),
            )
            .returning(DocumentRow.retry_count)
        )
        result = await self._session.execute(stmt)
        new_count = result.scalar_one_or_none()
        return int(new_count) if new_count is not None else 0

    # ------------------------------------------------------------------
    # Nested JSONB updates
    # ------------------------------------------------------------------

    async def update_extracted_data(self, id: str, extracted_data: dict[str, Any]) -> bool:
        return await self.update(
            id, {"extracted": extracted_data, "status": DocumentStatus.EXTRACTED.value}
        )

    async def update_sap_validation(self, id: str, validation_data: dict[str, Any], *, is_valid: bool = True) -> bool:
        status = DocumentStatus.VALIDATED if is_valid else DocumentStatus.FAILED
        return await self.update(
            id, {"sap_validation": validation_data, "status": status.value}
        )

    async def update_grn_posting(self, id: str, posting_data: dict[str, Any]) -> bool:
        new_status = (
            DocumentStatus.GR_POSTED
            if posting_data.get("status") == "success"
            else DocumentStatus.VALIDATED
        )
        return await self.update(id, {"grn_posting": posting_data, "status": new_status.value})

    async def update_miro_posting(self, id: str, posting_data: dict[str, Any]) -> bool:
        new_status = (
            DocumentStatus.POSTED
            if posting_data.get("status") == "success"
            else DocumentStatus.VALIDATED
        )
        return await self.update(id, {"miro_posting": posting_data, "status": new_status.value})

    async def update_fb60_posting(self, id: str, posting_data: dict[str, Any]) -> bool:
        new_status = (
            DocumentStatus.POSTED
            if posting_data.get("status") == "success"
            else DocumentStatus.EXTRACTED
        )
        return await self.update(id, {"fb60_posting": posting_data, "status": new_status.value})

    async def update_f26_simulation(self, id: str, sim_data: dict[str, Any]) -> bool:
        return await self.update(id, {"f26_simulation": sim_data, "status": DocumentStatus.SIMULATED.value})

    async def update_f26_posting(self, id: str, posting_data: dict[str, Any]) -> bool:
        new_status = (
            DocumentStatus.POSTED
            if posting_data.get("status") == "success"
            else DocumentStatus.SIMULATED
        )
        return await self.update(id, {"f26_posting": posting_data, "status": new_status.value})

    # ------------------------------------------------------------------
    # Paginated list view
    # ------------------------------------------------------------------

    async def list_documents(
        self,
        *,
        filter_query: dict[str, Any] | None = None,
        skip: int = 0,
        limit: int = 20,
        sort: list[tuple[str, int]] | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """Return (documents, total_count) for the list view."""
        fq = filter_query or {}
        srt = sort or [("uploaded_at", -1)]

        # Build base select — only columns needed for list view
        stmt = select(
            DocumentRow.id,
            DocumentRow.document_id,
            DocumentRow.type,
            DocumentRow.tcode,
            DocumentRow.status,
            DocumentRow.uploaded_at,
            DocumentRow.invoice_subtype,
            DocumentRow.extracted["vendor_name"].label("vendor_name"),
            DocumentRow.extracted["gross_amount"].label("gross_amount"),
            DocumentRow.grn_posting["grn_number"].label("grn_number"),
            DocumentRow.miro_posting["miro_number"].label("miro_number"),
            DocumentRow.fb60_posting["fb60_number"].label("fb60_number"),
        )

        # Apply simple equality filters (status, type, tcode, uploaded_by)
        for col_name, val in fq.items():
            if hasattr(DocumentRow, col_name):
                stmt = stmt.where(getattr(DocumentRow, col_name) == val)

        # Order
        for col_name, direction in srt:
            if hasattr(DocumentRow, col_name):
                col = getattr(DocumentRow, col_name)
                stmt = stmt.order_by(desc(col) if direction == -1 else asc(col))

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total_result = await self._session.execute(count_stmt)
        total = total_result.scalar_one()

        stmt = stmt.offset(skip).limit(limit)
        result = await self._session.execute(stmt)
        rows = result.mappings().all()

        docs = [
            {
                "id":              str(r["id"]),
                "document_id":     r["document_id"],
                "type":            r["type"],
                "tcode":           r["tcode"],
                "status":          r["status"],
                "uploaded_at":     r["uploaded_at"],
                "invoice_subtype": r["invoice_subtype"],
                "extracted": {
                    "vendor_name":  r["vendor_name"],
                    "gross_amount": r["gross_amount"],
                },
                "grn_posting":  {"grn_number":  r["grn_number"]}  if r["grn_number"]  else None,
                "miro_posting": {"miro_number": r["miro_number"]} if r["miro_number"] else None,
                "fb60_posting": {"fb60_number": r["fb60_number"]} if r["fb60_number"] else None,
            }
            for r in rows
        ]
        return docs, total

    # ------------------------------------------------------------------
    # Full-text / ILIKE search
    # ------------------------------------------------------------------

    async def search_documents(
        self,
        search: str,
        filter_query: dict[str, Any] | None = None,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        """Search document_id and vendor_name with ILIKE, respecting filter_query."""
        fq = filter_query or {}
        pattern = f"%{search}%"

        stmt = select(
            DocumentRow.id,
            DocumentRow.document_id,
            DocumentRow.type,
            DocumentRow.tcode,
            DocumentRow.status,
            DocumentRow.uploaded_at,
            DocumentRow.invoice_subtype,
            DocumentRow.extracted["vendor_name"].label("vendor_name"),
            DocumentRow.extracted["gross_amount"].label("gross_amount"),
            DocumentRow.grn_posting["grn_number"].label("grn_number"),
            DocumentRow.miro_posting["miro_number"].label("miro_number"),
            DocumentRow.fb60_posting["fb60_number"].label("fb60_number"),
        ).where(
            DocumentRow.document_id.ilike(pattern)
            | DocumentRow.extracted["vendor_name"].as_string().ilike(pattern)
        )

        for col_name, val in fq.items():
            if hasattr(DocumentRow, col_name):
                stmt = stmt.where(getattr(DocumentRow, col_name) == val)

        stmt = stmt.order_by(desc(DocumentRow.uploaded_at))

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self._session.execute(count_stmt)).scalar_one()

        result = await self._session.execute(stmt.offset(skip).limit(limit))
        rows = result.mappings().all()

        docs = [
            {
                "id":              str(r["id"]),
                "document_id":     r["document_id"],
                "type":            r["type"],
                "tcode":           r["tcode"],
                "status":          r["status"],
                "uploaded_at":     r["uploaded_at"],
                "invoice_subtype": r["invoice_subtype"],
                "extracted": {
                    "vendor_name":  r["vendor_name"],
                    "gross_amount": r["gross_amount"],
                },
                "grn_posting":  {"grn_number":  r["grn_number"]}  if r["grn_number"]  else None,
                "miro_posting": {"miro_number": r["miro_number"]} if r["miro_number"] else None,
                "fb60_posting": {"fb60_number": r["fb60_number"]} if r["fb60_number"] else None,
            }
            for r in rows
        ]
        return docs, total

    # ------------------------------------------------------------------
    # Dashboard metrics
    # ------------------------------------------------------------------

    async def get_dashboard_metrics(self) -> dict[str, Any]:
        """Return counts by status, by tcode, by type, total value, and trend."""
        # by_status
        status_result = await self._session.execute(
            select(DocumentRow.status, func.count().label("count"))
            .group_by(DocumentRow.status)
            .order_by(DocumentRow.status)
        )
        by_status = {r.status: r.count for r in status_result}

        # by_tcode
        tcode_result = await self._session.execute(
            select(DocumentRow.tcode, func.count().label("count"))
            .group_by(DocumentRow.tcode)
            .order_by(DocumentRow.tcode)
        )
        by_tcode = {r.tcode: r.count for r in tcode_result}

        # by_type
        type_result = await self._session.execute(
            select(DocumentRow.type, func.count().label("count"))
            .group_by(DocumentRow.type)
            .order_by(DocumentRow.type)
        )
        by_type = {r.type: r.count for r in type_result}

        # total value + total documents
        value_result = await self._session.execute(
            select(
                func.count().label("total_documents"),
                func.coalesce(
                    func.sum(
                        cast(
                            func.coalesce(
                                DocumentRow.extracted["gross_amount"].as_string(), "0"
                            ),
                            Numeric,
                        )
                    ),
                    0,
                ).label("total_value"),
            )
        )
        value_row = value_result.mappings().first() or {}

        # recent trend (last 30 days, grouped by date)
        trend_result = await self._session.execute(
            select(
                func.to_char(DocumentRow.uploaded_at, "YYYY-MM-DD").label("_id"),
                func.count().label("count"),
            )
            .group_by(text("1"))
            .order_by(desc(text("1")))
            .limit(30)
        )
        recent_trend = [{"_id": r._id, "count": r.count} for r in trend_result]

        return {
            "by_status":       by_status,
            "by_tcode":        by_tcode,
            "by_type":         by_type,
            "total_documents": value_row.get("total_documents", 0),
            "total_value":     round(float(value_row.get("total_value") or 0), 2),
            "recent_trend":    recent_trend,
        }
