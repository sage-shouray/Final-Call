"""UserRepository — account lookup and session management."""
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.user import UserRow
from src.repositories.base import BaseRepository

log = structlog.get_logger(__name__)


class UserRepository(BaseRepository[UserRow]):
    _model = UserRow

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def find_by_email(self, email: str) -> dict[str, Any] | None:
        """Case-insensitive lookup by email address (returns dict with hashed_password)."""
        from sqlalchemy import select
        stmt = select(UserRow).where(UserRow.email == email.lower().strip())
        res = await self._session.execute(stmt)
        user_row = res.scalars().first()
        return user_row.to_dict(include_password=True) if user_row else None

    async def update_last_login(self, id: str) -> bool:
        return await self.update(id, {"last_login": datetime.now(UTC)})

    async def find_active_users(self) -> list[dict[str, Any]]:
        return await self.list(filter={"is_active": True})

    async def deactivate(self, id: str) -> bool:
        return await self.update(id, {"is_active": False})

    async def set_role(self, id: str, role: str) -> bool:
        return await self.update(id, {"role": role})
