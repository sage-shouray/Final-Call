"""User model — maps to the 'users' PostgreSQL table."""
import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import EmailStr, Field
from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, PydanticBase, TimestampMixin, _utcnow


class UserRole(StrEnum):
    ADMIN    = "admin"
    MANAGER  = "manager"
    OPERATOR = "operator"


# ---------------------------------------------------------------------------
# SQLAlchemy ORM table
# ---------------------------------------------------------------------------


class UserRow(Base, TimestampMixin):
    """PostgreSQL users table."""

    __tablename__ = "users"

    id:              Mapped[str]          = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    email:           Mapped[str]          = mapped_column(String, unique=True, nullable=False)
    name:            Mapped[str]          = mapped_column(String, nullable=False)
    hashed_password: Mapped[str]          = mapped_column(String, nullable=False)
    role:            Mapped[str]          = mapped_column(String, nullable=False, default="operator")
    is_active:       Mapped[bool]         = mapped_column(Boolean, nullable=False, default=True)
    last_login:      Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    tenant_id:       Mapped[str | None]   = mapped_column(String, nullable=True)

    def to_dict(self, *, include_password: bool = False) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id":         self.id,
            "email":      self.email,
            "name":       self.name,
            "role":       self.role,
            "is_active":  self.is_active,
            "tenant_id":  self.tenant_id,
            "last_login": self.last_login.isoformat() if self.last_login else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_password:
            d["hashed_password"] = self.hashed_password
        return d


# ---------------------------------------------------------------------------
# Pydantic schema (used in auth service / token payloads)
# ---------------------------------------------------------------------------


class UserSchema(PydanticBase):
    """Lightweight read model — never exposes hashed_password."""

    id:         str
    email:      EmailStr
    name:       str
    role:       UserRole  = UserRole.OPERATOR
    is_active:  bool      = True
    last_login: datetime | None = None


# Backwards-compat alias so existing imports work
User = UserSchema
