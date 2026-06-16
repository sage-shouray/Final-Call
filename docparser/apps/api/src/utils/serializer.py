"""Recursively convert MongoDB wire types to JSON-safe Python primitives.

Motor returns ObjectId, Decimal128, and datetime objects from queries.
This module provides a single entry-point used by routers before handing
data to Pydantic response models.
"""
from datetime import datetime
from decimal import Decimal
from typing import Any

from bson import Decimal128, ObjectId


def serialize_doc(value: Any) -> Any:  # noqa: ANN401
    """Recursively normalise MongoDB types into JSON-serialisable values."""
    if isinstance(value, dict):
        return {k: serialize_doc(v) for k, v in value.items()}
    if isinstance(value, list):
        return [serialize_doc(item) for item in value]
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, Decimal128):
        return str(value.to_decimal())
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value
