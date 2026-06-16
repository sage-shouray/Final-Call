"""Shared Pydantic v2 base classes and the PyObjectId helper."""
from datetime import UTC, datetime
from typing import Annotated, Any

from bson import ObjectId
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field


def _coerce_object_id(v: Any) -> ObjectId:  # noqa: ANN401
    if isinstance(v, ObjectId):
        return v
    if isinstance(v, str) and ObjectId.is_valid(v):
        return ObjectId(v)
    raise ValueError(f"Invalid ObjectId: {v!r}")


# Annotated type used in model fields — serialises to str in JSON responses
PyObjectId = Annotated[ObjectId, BeforeValidator(_coerce_object_id)]


def _utcnow() -> datetime:
    return datetime.now(UTC)


class MongoModel(BaseModel):
    """Base for all MongoDB document models.

    - Accepts both '_id' (from Mongo wire) and 'id' (from API input).
    - Serialises ObjectId as str automatically.
    - Populates fields from aliases so Motor dicts work out of the box.
    """

    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True,
        # ObjectId → str when .model_dump(mode="json") or JSON serialisation
        json_encoders={ObjectId: str},
    )

    id: PyObjectId = Field(default_factory=ObjectId, alias="_id")

    def to_mongo(self) -> dict[str, Any]:
        """Return a dict suitable for insertion / replacement in MongoDB."""
        data = self.model_dump(by_alias=True, exclude_none=False)
        # Ensure _id is an ObjectId, not a str
        if isinstance(data.get("_id"), str):
            data["_id"] = ObjectId(data["_id"])
        return data


class TimestampedModel(MongoModel):
    """Adds auto-managed created_at / updated_at timestamps."""

    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
