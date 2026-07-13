"""Shared base classes for SQLAlchemy ORM tables and Pydantic schema models."""
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict
from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """SQLAlchemy declarative base for all ORM table models."""
    pass


class TimestampMixin:
    """Auto-managed created_at / updated_at columns."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        server_default=func.now(),
        onupdate=_utcnow,
    )


class PydanticBase(BaseModel):
    """Shared config for all Pydantic domain / schema models."""

    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True,
    )
