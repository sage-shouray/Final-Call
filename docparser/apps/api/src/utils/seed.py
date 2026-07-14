"""Seed the super-admin user from environment variables.

Idempotent — skips creation if the email already exists.
Called automatically on startup via lifespan, and can also be run manually:

    python -m src.utils.seed
"""
import asyncio
import logging

import structlog
from sqlalchemy import select

from src.config import settings
from src.database import AsyncSessionLocal, close_db, connect_db
from src.models.user import UserRow
from src.services.auth_service import auth_service

structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.DEBUG),
)
log = structlog.get_logger(__name__)


async def seed_super_admin() -> None:
    """Ensure the super-admin user exists. Safe to call on every startup."""
    email    = settings.SUPER_ADMIN_EMAIL.strip().lower()
    name     = settings.SUPER_ADMIN_NAME.strip()
    password = settings.SUPER_ADMIN_PASSWORD.get_secret_value()

    async with AsyncSessionLocal() as session:
        existing = (await session.execute(
            select(UserRow).where(UserRow.email == email)
        )).scalar_one_or_none()

        if existing:
            # If role somehow got downgraded, fix it silently
            if existing.role != "admin":
                existing.role = "admin"
                await session.commit()
                log.info("super-admin role restored", email=email)
            else:
                log.info("super-admin already exists — skipped", email=email)
            return

        hashed = auth_service.hash_password(password)
        user = UserRow(
            email=email,
            name=name,
            hashed_password=hashed,
            role="admin",
            is_active=True,
            tenant_id=None,   # super admin belongs to no tenant
        )
        session.add(user)
        await session.commit()
        log.info("super-admin created", email=email)


async def _run_standalone() -> None:
    await connect_db()
    try:
        await seed_super_admin()
    finally:
        await close_db()


if __name__ == "__main__":
    asyncio.run(_run_standalone())
