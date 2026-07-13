"""One-shot MongoDB → PostgreSQL data migration script.

Run ONCE after:
  1. PostgreSQL schema is created via:  alembic upgrade head
  2. Both MONGODB_URL and DATABASE_URL are set in the environment / .env

Usage::

    python scripts/migrate_mongo_to_pg.py

The script is idempotent: documents/users/audit_logs already in PostgreSQL
(matched by document_id / email / audit_log action+timestamp) are skipped.
"""
import asyncio
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from decimal import Decimal

# ── MongoDB (Motor) ───────────────────────────────────────────────────────────
try:
    from motor.motor_asyncio import AsyncIOMotorClient
except ImportError:
    print("ERROR: motor is not installed.  pip install motor pymongo")
    sys.exit(1)

# ── PostgreSQL (asyncpg) ──────────────────────────────────────────────────────
import asyncpg

MONGO_URL = os.environ.get("MONGODB_URL", "mongodb://localhost:27017")
MONGO_DB  = os.environ.get("MONGODB_DB_NAME", "docparser")
PG_URL    = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/docparser",
).replace("postgresql+asyncpg://", "postgresql://")


def _serial(obj):
    """JSON-serialise types that standard json can't handle."""
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    if hasattr(obj, "__str__"):  # ObjectId, etc.
        return str(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def _to_json(obj) -> str:
    return json.dumps(obj, default=_serial)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def migrate_documents(mongo_db, pg: asyncpg.Connection) -> int:
    print("Migrating documents …")
    count = 0
    async for doc in mongo_db["documents"].find({}):
        doc_id = doc.get("document_id", "")
        if not doc_id:
            continue

        # Check if already migrated
        existing = await pg.fetchval(
            "SELECT id FROM documents WHERE document_id = $1", doc_id
        )
        if existing:
            continue

        row_id = str(doc.get("_id", uuid.uuid4()))
        try:
            row_id = str(doc["_id"])
        except Exception:
            row_id = str(uuid.uuid4())

        await pg.execute(
            """
            INSERT INTO documents (
                id, document_id, type, tcode, invoice_subtype, status,
                uploaded_by, uploaded_at, file, extracted, sap_validation,
                grn_posting, miro_posting, fb60_posting, so_simulation, so_posting,
                retry_count, error_log, created_at, updated_at
            ) VALUES (
                $1,$2,$3,$4,$5,$6,$7,$8,
                $9::jsonb,$10::jsonb,$11::jsonb,$12::jsonb,$13::jsonb,
                $14::jsonb,$15::jsonb,$16::jsonb,
                $17,$18::jsonb,$19,$20
            )
            ON CONFLICT (document_id) DO NOTHING
            """,
            str(uuid.uuid4()),
            doc_id,
            doc.get("type", ""),
            doc.get("tcode", ""),
            doc.get("invoice_subtype"),
            doc.get("status", "uploaded"),
            doc.get("uploaded_by", ""),
            doc.get("uploaded_at", _utcnow()),
            _to_json(doc.get("file") or {}),
            _to_json(doc.get("extracted")) if doc.get("extracted") else None,
            _to_json(doc.get("sap_validation")) if doc.get("sap_validation") else None,
            _to_json(doc.get("grn_posting")) if doc.get("grn_posting") else None,
            _to_json(doc.get("miro_posting")) if doc.get("miro_posting") else None,
            _to_json(doc.get("fb60_posting")) if doc.get("fb60_posting") else None,
            _to_json(doc.get("so_simulation")) if doc.get("so_simulation") else None,
            _to_json(doc.get("so_posting")) if doc.get("so_posting") else None,
            int(doc.get("retry_count", 0)),
            _to_json(doc.get("error_log") or []),
            doc.get("created_at", _utcnow()),
            doc.get("updated_at", _utcnow()),
        )
        count += 1
        if count % 100 == 0:
            print(f"  … {count} documents migrated")
    return count


async def migrate_users(mongo_db, pg: asyncpg.Connection) -> int:
    print("Migrating users …")
    count = 0
    async for user in mongo_db["users"].find({}):
        email = (user.get("email") or "").lower().strip()
        if not email:
            continue

        existing = await pg.fetchval("SELECT id FROM users WHERE email = $1", email)
        if existing:
            continue

        await pg.execute(
            """
            INSERT INTO users (
                id, email, name, hashed_password, role, is_active,
                last_login, created_at, updated_at
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
            ON CONFLICT (email) DO NOTHING
            """,
            str(uuid.uuid4()),
            email,
            user.get("name", ""),
            user.get("hashed_password", ""),
            user.get("role", "operator"),
            bool(user.get("is_active", True)),
            user.get("last_login"),
            user.get("created_at", _utcnow()),
            user.get("updated_at", _utcnow()),
        )
        count += 1
    return count


async def migrate_audit_logs(mongo_db, pg: asyncpg.Connection) -> int:
    print("Migrating audit logs …")
    count = 0
    async for log in mongo_db["audit_logs"].find({}):
        doc_id = log.get("document_id", "")
        action = log.get("action", "")

        await pg.execute(
            """
            INSERT INTO audit_logs (
                id, document_id, action, performed_by, timestamp, details, ip_address
            ) VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7)
            """,
            str(uuid.uuid4()),
            doc_id,
            action,
            log.get("performed_by", ""),
            log.get("timestamp", _utcnow()),
            _to_json(log.get("details") or {}),
            log.get("ip_address", ""),
        )
        count += 1
        if count % 500 == 0:
            print(f"  … {count} audit logs migrated")
    return count


async def migrate_customers(mongo_db, pg: asyncpg.Connection) -> int:
    print("Migrating customers …")
    count = 0
    async for c in mongo_db["customers"].find({}):
        cid = c.get("CUSTOMER") or c.get("customer")
        if not cid:
            continue
        c.pop("_id", None)
        await pg.execute(
            """
            INSERT INTO customers (id, customer_id, data)
            VALUES ($1, $2, $3::jsonb)
            ON CONFLICT (customer_id) DO UPDATE SET data = EXCLUDED.data
            """,
            str(uuid.uuid4()),
            str(cid),
            _to_json(c),
        )
        count += 1
    return count


async def main() -> None:
    print(f"Connecting to MongoDB: {MONGO_URL}/{MONGO_DB}")
    mongo_client = AsyncIOMotorClient(MONGO_URL)
    mongo_db = mongo_client[MONGO_DB]

    print(f"Connecting to PostgreSQL: {PG_URL}")
    pg = await asyncpg.connect(PG_URL)

    try:
        docs   = await migrate_documents(mongo_db, pg)
        users  = await migrate_users(mongo_db, pg)
        audits = await migrate_audit_logs(mongo_db, pg)
        custs  = await migrate_customers(mongo_db, pg)

        print("\n✓ Migration complete:")
        print(f"  Documents:   {docs}")
        print(f"  Users:       {users}")
        print(f"  Audit logs:  {audits}")
        print(f"  Customers:   {custs}")
    finally:
        await pg.close()
        mongo_client.close()


if __name__ == "__main__":
    asyncio.run(main())
