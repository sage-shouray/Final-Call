"""DocParser FastAPI application — entrypoint and wiring."""
import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import sentry_sdk
import structlog
from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration

from sqlalchemy import text

from src.config import settings
from src.database import close_db, connect_db, engine
from src.utils.redis_client import close_redis, connect_redis

# ---------------------------------------------------------------------------
# Logging — configure structlog before any loggers are created
# ---------------------------------------------------------------------------

def _configure_logging() -> None:
    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    if settings.DEBUG:
        renderer = structlog.dev.ConsoleRenderer(colors=True)
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(settings.LOG_LEVEL)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


_configure_logging()
log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Sentry — initialise once at module load (before app creation)
# ---------------------------------------------------------------------------

if settings.SENTRY_DSN:
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.ENV,
        release=f"docparser@{settings.APP_VERSION}",
        traces_sample_rate=0.2,
        integrations=[
            StarletteIntegration(transaction_style="endpoint"),
            FastApiIntegration(transaction_style="endpoint"),
        ],
        # Never send PII to Sentry
        send_default_pii=False,
    )
    log.info("Sentry initialised", env=settings.ENV)

# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    log.info("DocParser API starting", version=settings.APP_VERSION, env=settings.ENV)
    try:
        await connect_db()
    except Exception as exc:
        log.warning("PostgreSQL unavailable at startup — will retry on first request", error=str(exc))
    try:
        await connect_redis()
    except Exception as exc:
        log.warning("Redis unavailable — token blacklisting disabled", error=str(exc))

    # Seed super-admin from env (idempotent)
    try:
        from src.utils.seed import seed_super_admin
        await seed_super_admin()
    except Exception as exc:
        log.warning("Super-admin seed failed (non-fatal)", error=str(exc))

    # Idempotent schema migrations — add any new columns without alembic
    try:
        async with engine.begin() as _conn:
            await _conn.execute(text(
                "ALTER TABLE documents ADD COLUMN IF NOT EXISTS tenant_id VARCHAR"
            ))
            await _conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_documents_tenant_id ON documents(tenant_id)"
            ))
            await _conn.execute(text(
                "ALTER TABLE audit_logs ALTER COLUMN document_id DROP NOT NULL"
            ))
            await _conn.execute(text(
                "ALTER TABLE documents ADD COLUMN IF NOT EXISTS miro_parking JSONB"
            ))
            await _conn.execute(text(
                "ALTER TABLE documents ADD COLUMN IF NOT EXISTS source VARCHAR NOT NULL DEFAULT 'web'"
            ))
            await _conn.execute(text(
                "ALTER TABLE documents ADD COLUMN IF NOT EXISTS source_reference VARCHAR NOT NULL DEFAULT ''"
            ))
            await _conn.execute(text(
                "ALTER TABLE documents ADD COLUMN IF NOT EXISTS source_metadata JSONB NOT NULL DEFAULT '{}'::jsonb"
            ))
            await _conn.execute(text('''
                CREATE TABLE IF NOT EXISTS tenant_mailboxes (
                    id VARCHAR PRIMARY KEY,
                    tenant_id VARCHAR NOT NULL,
                    provider VARCHAR NOT NULL DEFAULT 'imap',
                    label VARCHAR NOT NULL DEFAULT '',
                    address VARCHAR NOT NULL DEFAULT '',
                    credentials_enc TEXT NOT NULL DEFAULT '',
                    folder VARCHAR NOT NULL DEFAULT 'INBOX',
                    poll_interval_s INTEGER NOT NULL DEFAULT 60,
                    enabled BOOLEAN NOT NULL DEFAULT FALSE,
                    sender_allowlist JSONB NOT NULL DEFAULT '[]'::jsonb,
                    auto_post_enabled BOOLEAN NOT NULL DEFAULT FALSE,
                    last_polled_at TIMESTAMPTZ,
                    last_success_at TIMESTAMPTZ,
                    last_error TEXT NOT NULL DEFAULT '',
                    consecutive_failures INTEGER NOT NULL DEFAULT 0,
                    messages_seen INTEGER NOT NULL DEFAULT 0,
                    documents_ingested INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )'''))
            await _conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_mailboxes_tenant ON tenant_mailboxes(tenant_id)"
            ))
            await _conn.execute(text('''
                CREATE TABLE IF NOT EXISTS mailbox_seen_messages (
                    id VARCHAR PRIMARY KEY,
                    mailbox_id VARCHAR NOT NULL,
                    message_id VARCHAR NOT NULL,
                    subject TEXT NOT NULL DEFAULT '',
                    sender VARCHAR NOT NULL DEFAULT '',
                    received_at TIMESTAMPTZ,
                    outcome VARCHAR NOT NULL DEFAULT '',
                    document_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
                    processed_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )'''))
            # The dedup lookup on every message: mailbox + message id.
            await _conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_seen_message "
                "ON mailbox_seen_messages(mailbox_id, message_id)"
            ))

            # Deduplication reads file->>'fingerprint' on every ingest.
            await _conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_documents_fingerprint "
                "ON documents ((file->>'fingerprint'))"
            ))
            # Per-tenant SAP endpoint: the full URL as that customer exposes it,
            # plus their own request shape. Replaces the assumption of one shared
            # host on client 800.
            await _conn.execute(text(
                "ALTER TABLE tenant_api_configs ADD COLUMN IF NOT EXISTS full_url VARCHAR NOT NULL DEFAULT ''"
            ))
            await _conn.execute(text(
                "ALTER TABLE tenant_api_configs ADD COLUMN IF NOT EXISTS payload_template JSONB NOT NULL DEFAULT '{}'::jsonb"
            ))
            await _conn.execute(text(
                "ALTER TABLE documents ADD COLUMN IF NOT EXISTS pipeline JSONB"
            ))
        log.info("Schema migrations applied")
    except Exception as exc:
        log.warning("Schema migration failed (non-fatal)", error=str(exc))

    # Start background workers in the FastAPI event loop
    from src.workers.change_stream_worker import start_change_stream_worker
    from src.workers.event_consumer import start_event_consumer
    from src.workers.mail_worker import start_mail_worker

    consumer_task = asyncio.create_task(start_event_consumer(), name="event-consumer")
    change_stream_task = asyncio.create_task(
        start_change_stream_worker(), name="change-stream"
    )
    mail_task = asyncio.create_task(start_mail_worker(), name="mail-ingest")
    log.info("Background workers started")

    yield

    # Graceful shutdown: cancel background tasks then close infra connections
    consumer_task.cancel()
    change_stream_task.cancel()
    mail_task.cancel()
    for task in (consumer_task, change_stream_task, mail_task):
        try:
            await task
        except asyncio.CancelledError:
            pass
    log.info("Background workers stopped")

    await close_db()
    try:
        await close_redis()
    except Exception:
        pass
    log.info("DocParser API stopped cleanly")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="DocParser API",
    description="Intelligent SAP Document Processing Service",
    version=settings.APP_VERSION,
    docs_url="/api/docs" if not settings.is_production else None,
    redoc_url="/api/redoc" if not settings.is_production else None,
    openapi_url="/api/openapi.json" if not settings.is_production else None,
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# Exception handlers  (registered before middleware so they catch everything)
# ---------------------------------------------------------------------------

from src.middleware.error_handler import setup_exception_handlers  # noqa: E402

setup_exception_handlers(app)

# ---------------------------------------------------------------------------
# Middleware stack
#
# FastAPI/Starlette uses LIFO ordering: the LAST add_middleware call becomes
# the OUTERMOST wrapper (runs first on the way in, last on the way out).
#
# Desired execution order (request →):
#   CORSMiddleware → GZipMiddleware → RequestLoggingMiddleware
#   → AuthMiddleware → RateLimitMiddleware → route handler
#
# So we add them innermost-first:
# ---------------------------------------------------------------------------

from src.middleware.auth import AuthMiddleware  # noqa: E402
from src.middleware.logging import RequestLoggingMiddleware  # noqa: E402
from src.middleware.rate_limit import RateLimitMiddleware  # noqa: E402
from src.middleware.security_headers import SecurityHeadersMiddleware  # noqa: E402
from starlette.middleware.cors import CORSMiddleware  # noqa: E402

# 1 — innermost: RateLimit (needs request.state.user set by Auth)
app.add_middleware(RateLimitMiddleware)

# 2 — Auth sets request.state.user for everything inside it
app.add_middleware(AuthMiddleware)

# 3 — Logging generates request_id and wraps timing around Auth + RateLimit
app.add_middleware(RequestLoggingMiddleware)

# 4 — Security headers on every response
app.add_middleware(SecurityHeadersMiddleware)

# 5 — Gzip compresses outbound responses
app.add_middleware(GZipMiddleware, minimum_size=1_000)

# 6 — outermost: CORS sets response headers before anything else runs
app.add_middleware(
    CORSMiddleware,
    allow_origins=[str(o) for o in settings.CORS_ORIGINS],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "X-RateLimit-Limit", "X-RateLimit-Remaining"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

from src.routers import auth, customers, dashboard, documents, health, websocket  # noqa: E402
from src.routers import admin, mailboxes  # noqa: E402

app.include_router(health.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(documents.router, prefix="/api")
app.include_router(customers.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(websocket.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(mailboxes.router, prefix="/api")
