"""User model — maps to the 'users' MongoDB collection."""
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import EmailStr, Field

from src.models.base import TimestampedModel, _utcnow


class UserRole(StrEnum):
    ADMIN = "admin"
    MANAGER = "manager"
    OPERATOR = "operator"


class User(TimestampedModel):
    """MongoDB document for the 'users' collection.

    hashed_password is excluded from default serialisation (model_dump / JSON
    responses) via Field(exclude=True).  to_mongo() overrides this so the
    hash IS written to MongoDB — it must never be skipped on persistence.
    """

    email: EmailStr
    name: str
    # exclude=True keeps this field out of API responses; to_mongo() re-adds it.
    hashed_password: str = Field(..., exclude=True)
    role: UserRole = UserRole.OPERATOR
    is_active: bool = True
    last_login: datetime | None = None

    def to_mongo(self) -> dict[str, Any]:
        data = super().to_mongo()
        # Explicitly include the excluded field for DB persistence
        data["hashed_password"] = self.hashed_password
        return data
