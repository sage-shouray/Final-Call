"""Seed script — creates default admin and operator accounts.

Idempotent: existing users (matched by email) are skipped.

Usage::

    # From apps/api directory with virtualenv active
    python -m src.utils.seed
"""
import asyncio
import logging

import structlog

from src.database import AsyncSessionLocal, connect_db, close_db
from src.models.user import UserRole, UserRow
from src.repositories.user_repository import UserRepository
from src.services.auth_service import auth_service
from src.utils.redis_client import close_redis, connect_redis

structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.DEBUG),
)
log = structlog.get_logger(__name__)

_SEED_USERS: list[dict] = [
    {
        "email":    "admin@docparser.com",
        "name":     "DocParser Admin",
        "password": "Admin@123",
        "role":     UserRole.ADMIN,
    },
    {
        "email":    "operator@docparser.com",
        "name":     "DocParser Operator",
        "password": "Operator@123",
        "role":     UserRole.OPERATOR,
    },
]


async def run_seed() -> None:
    await connect_db()

    try:
        await connect_redis()
        redis_ok = True
    except Exception as exc:
        log.warning("Redis unavailable — skipping (not needed for seed)", error=str(exc))
        redis_ok = False

    async with AsyncSessionLocal() as session:
        user_repo = UserRepository(session)

        for seed_data in _SEED_USERS:
            email: str = seed_data["email"]
            existing = await user_repo.find_by_email(email)

            if existing:
                log.info("skipped — user already exists", email=email)
                continue

            inserted_id = await user_repo.create(
                {
                    "email":           email.lower().strip(),
                    "name":            seed_data["name"],
                    "hashed_password": auth_service.hash_password(seed_data["password"]),
                    "role":            seed_data["role"].value,
                }
            )

            log.info("created seed user", email=email, role=seed_data["role"], id=inserted_id)

        await session.commit()

    await close_db()
    if redis_ok:
        await close_redis()
    log.info("seed complete")


if __name__ == "__main__":
    asyncio.run(run_seed())
