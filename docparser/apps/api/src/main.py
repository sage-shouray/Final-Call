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

    # Idempotent schema migrations — add any new columns without alembic.
    #
    # Each statement runs in its OWN transaction, not one shared one. That
    # used to mean a single missing table anywhere in this list — a genuine
    # gap, since tenant_api_configs was never created by alembic's initial
    # migration at all — rolled back every other statement in the batch too,
    # including ones that had already succeeded. The users.tenant_id column
    # was being added correctly on every boot and then silently discarded a
    # few statements later for a completely unrelated reason. Isolating each
    # statement means one gap blocks only the thing it actually affects.
    _migrations: list[tuple[str, str]] = [
        # Three more tables in the same missing-from-alembic category as
        # tenant_api_configs below, found when creating a company failed
        # outright — TenantRow is the very first insert that path makes.
        ("tenants table", '''
            CREATE TABLE IF NOT EXISTS tenants (
                id VARCHAR PRIMARY KEY,
                name VARCHAR NOT NULL,
                slug VARCHAR NOT NULL,
                gstin VARCHAR NOT NULL DEFAULT '',
                email VARCHAR NOT NULL DEFAULT '',
                phone VARCHAR NOT NULL DEFAULT '',
                address VARCHAR NOT NULL DEFAULT '',
                status VARCHAR NOT NULL DEFAULT 'active',
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )'''),
        ("tenants.slug unique index",
         "CREATE UNIQUE INDEX IF NOT EXISTS ix_tenants_slug ON tenants(slug)"),
        ("pricing_configs table", '''
            CREATE TABLE IF NOT EXISTS pricing_configs (
                id VARCHAR PRIMARY KEY,
                tenant_id VARCHAR NOT NULL,
                tcode VARCHAR NOT NULL,
                label VARCHAR NOT NULL DEFAULT '',
                price_per_document NUMERIC(10, 2) NOT NULL DEFAULT 0
            )'''),
        ("pricing_configs.tenant_id index",
         "CREATE INDEX IF NOT EXISTS ix_pricing_configs_tenant ON pricing_configs(tenant_id)"),
        ("billing_records table", '''
            CREATE TABLE IF NOT EXISTS billing_records (
                id VARCHAR PRIMARY KEY,
                tenant_id VARCHAR NOT NULL,
                period_month INTEGER NOT NULL,
                period_year INTEGER NOT NULL,
                tcode VARCHAR NOT NULL,
                doc_count INTEGER NOT NULL DEFAULT 0,
                price_each NUMERIC(10, 2) NOT NULL DEFAULT 0,
                total_amount NUMERIC(10, 2) NOT NULL DEFAULT 0,
                status VARCHAR NOT NULL DEFAULT 'pending',
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )'''),
        ("billing_records.tenant_id index",
         "CREATE INDEX IF NOT EXISTS ix_billing_records_tenant ON billing_records(tenant_id)"),
        ("documents.tenant_id",
         "ALTER TABLE documents ADD COLUMN IF NOT EXISTS tenant_id VARCHAR"),
        ("documents.tenant_id index",
         "CREATE INDEX IF NOT EXISTS ix_documents_tenant_id ON documents(tenant_id)"),
        # The User model declares this column (models/user.py), but neither
        # this block nor alembic's initial migration ever added it to the
        # real users table. Every query that selects a user, including the
        # login path and super-admin seeding, names this column explicitly
        # and fails outright without it.
        ("users.tenant_id",
         "ALTER TABLE users ADD COLUMN IF NOT EXISTS tenant_id VARCHAR"),
        ("users.tenant_id index",
         "CREATE INDEX IF NOT EXISTS ix_users_tenant_id ON users(tenant_id)"),
        ("audit_logs.document_id nullable",
         "ALTER TABLE audit_logs ALTER COLUMN document_id DROP NOT NULL"),
        ("documents.miro_parking",
         "ALTER TABLE documents ADD COLUMN IF NOT EXISTS miro_parking JSONB"),
        ("documents.source",
         "ALTER TABLE documents ADD COLUMN IF NOT EXISTS source VARCHAR NOT NULL DEFAULT 'web'"),
        ("documents.source_reference",
         "ALTER TABLE documents ADD COLUMN IF NOT EXISTS source_reference VARCHAR NOT NULL DEFAULT ''"),
        ("documents.source_metadata",
         "ALTER TABLE documents ADD COLUMN IF NOT EXISTS source_metadata JSONB NOT NULL DEFAULT '{}'::jsonb"),
        ("tenant_mailboxes table", '''
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
            )'''),
        ("tenant_mailboxes.tenant_id index",
         "CREATE INDEX IF NOT EXISTS ix_mailboxes_tenant ON tenant_mailboxes(tenant_id)"),
        ("tenant_mailboxes.tenant_routes",
         "ALTER TABLE tenant_mailboxes ADD COLUMN IF NOT EXISTS tenant_routes JSONB NOT NULL DEFAULT '[]'::jsonb"),
        ("sap_notifications table", '''
            CREATE TABLE IF NOT EXISTS sap_notifications (
                id VARCHAR PRIMARY KEY,
                po_number VARCHAR NOT NULL DEFAULT '',
                status VARCHAR NOT NULL DEFAULT '',
                message TEXT NOT NULL DEFAULT '',
                raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                processed BOOLEAN NOT NULL DEFAULT FALSE,
                attempts INTEGER NOT NULL DEFAULT 0,
                document_id VARCHAR NOT NULL DEFAULT '',
                result TEXT NOT NULL DEFAULT '',
                processed_at TIMESTAMPTZ,
                received_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )'''),
        ("sap_notifications.po_number index",
         "CREATE INDEX IF NOT EXISTS ix_sap_notif_po ON sap_notifications(po_number)"),
        ("sap_notifications.processed index",
         "CREATE INDEX IF NOT EXISTS ix_sap_notif_processed ON sap_notifications(processed)"),
        ("mailbox_seen_messages table", '''
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
            )'''),
        # The dedup lookup on every message: mailbox + message id.
        ("mailbox_seen_messages dedup index",
         "CREATE UNIQUE INDEX IF NOT EXISTS ux_seen_message "
         "ON mailbox_seen_messages(mailbox_id, message_id)"),
        # Deduplication reads file->>'fingerprint' on every ingest.
        ("documents fingerprint index",
         "CREATE INDEX IF NOT EXISTS ix_documents_fingerprint "
         "ON documents ((file->>'fingerprint'))"),
        # tenant_api_configs itself, not just columns on it: alembic's initial
        # migration never created this table at all — every ALTER below on it
        # was silently assuming a table that only ever existed on whichever
        # database first ran this code, never captured in a real migration.
        ("tenant_api_configs table", '''
            CREATE TABLE IF NOT EXISTS tenant_api_configs (
                id VARCHAR PRIMARY KEY,
                tenant_id VARCHAR NOT NULL,
                api_key VARCHAR NOT NULL,
                label VARCHAR NOT NULL DEFAULT '',
                workflow VARCHAR NOT NULL DEFAULT '',
                full_url VARCHAR NOT NULL DEFAULT '',
                base_url VARCHAR NOT NULL DEFAULT '',
                path VARCHAR NOT NULL DEFAULT '',
                method VARCHAR NOT NULL DEFAULT 'POST',
                sap_client VARCHAR NOT NULL DEFAULT '800',
                payload_template JSONB NOT NULL DEFAULT '{}'::jsonb,
                auth_type VARCHAR NOT NULL DEFAULT 'basic',
                username VARCHAR NOT NULL DEFAULT '',
                password VARCHAR NOT NULL DEFAULT '',
                extra_headers JSONB NOT NULL DEFAULT '{}'::jsonb,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                last_tested_at TIMESTAMPTZ,
                last_test_status VARCHAR
            )'''),
        # Per-tenant SAP endpoint: the full URL as that customer exposes it,
        # plus their own request shape. Replaces the assumption of one shared
        # host on client 800. Kept even though the CREATE TABLE above already
        # includes both columns — cheap no-ops on a fresh table, and still the
        # ones actually needed on any database where the table already existed
        # from before this fix.
        ("tenant_api_configs.full_url",
         "ALTER TABLE tenant_api_configs ADD COLUMN IF NOT EXISTS full_url VARCHAR NOT NULL DEFAULT ''"),
        ("tenant_api_configs.payload_template",
         "ALTER TABLE tenant_api_configs ADD COLUMN IF NOT EXISTS payload_template JSONB NOT NULL DEFAULT '{}'::jsonb"),
        ("documents.pipeline",
         "ALTER TABLE documents ADD COLUMN IF NOT EXISTS pipeline JSONB"),
        # Found by cross-referencing every model column against every table
        # actually created here and in alembic's initial migration — three
        # more genuine gaps, same root cause as everything else in this list.
        # page_count specifically is what broke the admin company list: it's
        # summed for every tenant on every load, so a company that had been
        # created successfully still failed to display at all.
        ("documents.page_count",
         "ALTER TABLE documents ADD COLUMN IF NOT EXISTS page_count INTEGER NOT NULL DEFAULT 0"),
        ("documents.f26_simulation",
         "ALTER TABLE documents ADD COLUMN IF NOT EXISTS f26_simulation JSONB"),
        ("documents.f26_posting",
         "ALTER TABLE documents ADD COLUMN IF NOT EXISTS f26_posting JSONB"),
    ]

    _failed: list[str] = []
    for _label, _sql in _migrations:
        try:
            async with engine.begin() as _conn:
                await _conn.execute(text(_sql))
        except Exception as exc:
            _failed.append(_label)
            log.warning("Schema migration step failed (non-fatal)", step=_label, error=str(exc))
    if _failed:
        log.warning("Schema migrations completed with failures", failed_steps=_failed)
    else:
        log.info("Schema migrations applied")

    # Start background workers in the FastAPI event loop
    from src.workers.change_stream_worker import start_change_stream_worker
    from src.workers.event_consumer import start_event_consumer
    from src.workers.mail_worker import start_mail_worker
    from src.workers.sap_notification_worker import start_sap_notification_worker

    consumer_task = asyncio.create_task(start_event_consumer(), name="event-consumer")
    change_stream_task = asyncio.create_task(
        start_change_stream_worker(), name="change-stream"
    )
    mail_task = asyncio.create_task(start_mail_worker(), name="mail-ingest")
    sap_notification_task = asyncio.create_task(
        start_sap_notification_worker(), name="sap-notifications"
    )
    log.info("Background workers started")

    yield

    # Graceful shutdown: cancel background tasks then close infra connections
    consumer_task.cancel()
    change_stream_task.cancel()
    mail_task.cancel()
    sap_notification_task.cancel()
    for task in (consumer_task, change_stream_task, mail_task, sap_notification_task):
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
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "X-RateLimit-Limit", "X-RateLimit-Remaining"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

from src.routers import auth, customers, dashboard, documents, health, websocket  # noqa: E402
from src.routers import admin, mailboxes, sap_notifications  # noqa: E402

app.include_router(health.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(documents.router, prefix="/api")
app.include_router(customers.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(websocket.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(mailboxes.router, prefix="/api")
app.include_router(sap_notifications.router, prefix="/api")
