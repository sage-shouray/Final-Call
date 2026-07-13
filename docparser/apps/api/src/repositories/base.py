"""Generic async repository providing CRUD primitives over a SQLAlchemy table."""
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.base import Base

log = structlog.get_logger(__name__)


class BaseRepository[T: Base]:
    """Async CRUD wrapper around a single SQLAlchemy ORM table.

    Concrete repositories extend this class with model-specific queries.
    All methods return plain dicts so the service layer stays model-agnostic.
    """

    _model: type[T]

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    async def create(self, data: dict[str, Any]) -> str:
        """Insert a row and return its id."""
        now = datetime.now(UTC)
        data.setdefault("created_at", now)
        data.setdefault("updated_at", now)
        row = self._model(**data)
        self._session.add(row)
        await self._session.flush()  # generates pk without committing
        inserted_id: str = str(row.id)  # type: ignore[attr-defined]
        log.debug("row created", table=self._model.__tablename__, id=inserted_id)
        return inserted_id

    async def update(self, id: str, update_data: dict[str, Any]) -> bool:
        """Patch a row by primary key using direct UPDATE.  Returns True when matched."""
        update_data["updated_at"] = datetime.now(UTC)
        result = await self._session.execute(
            update(self._model)
            .where(self._model.id == id)  # type: ignore[attr-defined]
            .values(**update_data)
            .returning(self._model.id)  # type: ignore[attr-defined]
        )
        return result.scalar_one_or_none() is not None

    async def delete(self, id: str) -> bool:
        """Hard-delete a row by primary key.  Returns True when deleted."""
        result = await self._session.execute(
            delete(self._model)
            .where(self._model.id == id)  # type: ignore[attr-defined]
            .returning(self._model.id)  # type: ignore[attr-defined]
        )
        return result.scalar_one_or_none() is not None

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    async def find_by_id(self, id: str) -> dict[str, Any] | None:
        row = await self._session.get(self._model, id)
        return row.to_dict() if row else None  # type: ignore[attr-defined]

    async def find_one(self, filter: dict[str, Any]) -> dict[str, Any] | None:
        """Find first row matching all equality conditions in filter."""
        stmt = select(self._model)
        for col, val in filter.items():
            stmt = stmt.where(getattr(self._model, col) == val)
        result = await self._session.execute(stmt)
        row = result.scalars().first()
        return row.to_dict() if row else None  # type: ignore[attr-defined]

    async def list(
        self,
        filter: dict[str, Any] | None = None,
        *,
        skip: int = 0,
        limit: int = 50,
        sort: list[tuple[str, int]] | None = None,
    ) -> list[dict[str, Any]]:
        stmt = select(self._model)
        for col, val in (filter or {}).items():
            stmt = stmt.where(getattr(self._model, col) == val)
        if sort:
            from sqlalchemy import asc, desc
            for col_name, direction in sort:
                col = getattr(self._model, col_name)
                stmt = stmt.order_by(desc(col) if direction == -1 else asc(col))
        stmt = stmt.offset(skip).limit(limit)
        result = await self._session.execute(stmt)
        return [row.to_dict() for row in result.scalars().all()]  # type: ignore[attr-defined]

    async def count(self, filter: dict[str, Any] | None = None) -> int:
        stmt = select(func.count()).select_from(self._model)
        for col, val in (filter or {}).items():
            stmt = stmt.where(getattr(self._model, col) == val)
        result = await self._session.execute(stmt)
        return result.scalar_one()

    async def find_one_and_update(
        self,
        filter: dict[str, Any],
        update_data: dict[str, Any],
        *,
        return_after: bool = True,
    ) -> dict[str, Any] | None:
        """Find one row, apply update_data via $set-equivalent, return updated row."""
        update_data["updated_at"] = datetime.now(UTC)
        stmt = select(self._model)
        for col, val in filter.items():
            stmt = stmt.where(getattr(self._model, col) == val)
        result = await self._session.execute(stmt)
        row: T | None = result.scalars().first()
        if row is None:
            return None
        for key, val in update_data.items():
            setattr(row, key, val)
        await self._session.flush()
        return row.to_dict()  # type: ignore[attr-defined]
