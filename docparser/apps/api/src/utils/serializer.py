"""Recursively convert Python types to JSON-safe primitives.

PostgreSQL / SQLAlchemy returns datetime and Decimal objects.
This replaces the old MongoDB-specific serialiser (ObjectId, Decimal128 removed).
"""
from datetime import datetime
from decimal import Decimal
from typing import Any


def serialize_doc(value: Any) -> Any:  # noqa: ANN401
    """Recursively normalise types into JSON-serialisable values."""
    if isinstance(value, dict):
        # Map 'id' → '_id' so existing frontend/router code that reads safe["_id"] still works
        result = {}
        for k, v in value.items():
            result[k] = serialize_doc(v)
        if "id" in result and "_id" not in result:
            result["_id"] = result["id"]
        return result
    if isinstance(value, list):
        return [serialize_doc(item) for item in value]
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value
