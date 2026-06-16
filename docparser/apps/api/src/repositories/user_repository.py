"""UserRepository — account lookup and session management."""
from datetime import UTC, datetime
from typing import Any

import structlog
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from src.repositories.base import BaseRepository

log = structlog.get_logger(__name__)

_COLLECTION = "users"


class UserRepository(BaseRepository):
    def __init__(self, db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
        super().__init__(_COLLECTION, db)

    async def find_by_email(self, email: str) -> dict[str, Any] | None:
        """Case-insensitive lookup by email address."""
        return await self.find_one({"email": email.lower().strip()})

    async def update_last_login(self, id: str) -> bool:
        """Stamp last_login with the current UTC time."""
        return await self.update(id, {"last_login": datetime.now(UTC)})

    async def find_active_users(self) -> list[dict[str, Any]]:
        return await self.list(filter={"is_active": True})

    async def deactivate(self, id: str) -> bool:
        return await self.update(id, {"is_active": False})

    async def set_role(self, id: str, role: str) -> bool:
        result = await self.find_one_and_update(
            {"_id": ObjectId(id)},
            {"$set": {"role": role, "updated_at": datetime.now(UTC)}},
        )
        return result is not None
