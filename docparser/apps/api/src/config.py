"""Application configuration via pydantic-settings."""
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import (
    AnyHttpUrl,
    Field,
    RedisDsn,
    SecretStr,
    field_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Both env files are real: docker-compose feeds the repo-root .env, while
    # local runs use apps/api/.env. A bare ".env" resolves against the *working
    # directory*, so the same command loaded different config (different
    # JWT_SECRET, different GEMINI_MODEL) depending on where it was launched
    # from — which silently served stale settings and was mistaken for code
    # changes breaking OCR. Both paths are now anchored to this file's location,
    # so the result no longer depends on cwd. Later files win, so apps/api/.env
    # keeps overriding the root for local development.
    model_config = SettingsConfigDict(
        env_file=(
            Path(__file__).resolve().parents[3] / ".env",   # docparser/.env  (docker)
            Path(__file__).resolve().parents[1] / ".env",   # apps/api/.env   (local)
        ),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # ── App ───────────────────────────────────────────────────────────────
    APP_VERSION: str = "0.1.0"
    ENV: Annotated[str, Field(pattern=r"^(development|staging|production)$")] = "development"
    DEBUG: bool = False
    SECRET_KEY: SecretStr = Field(default="change-me-in-production")
    # Encrypts credentials held on behalf of customers (mailbox passwords, OAuth
    # secrets). Generate with: python -c "from cryptography.fernet import Fernet;
    # print(Fernet.generate_key().decode())". Changing it makes stored
    # credentials unreadable and they must be re-entered.
    SECRET_ENCRYPTION_KEY: SecretStr = Field(default="")

    # ── Database — PostgreSQL ─────────────────────────────────────────────
    # Format: postgresql+asyncpg://user:password@host:port/dbname
    DATABASE_URL: str = Field(default="postgresql+asyncpg://postgres:postgres@localhost:5432/docparser")
    DB_POOL_SIZE: Annotated[int, Field(ge=1, le=100)] = 20
    DB_MAX_OVERFLOW: Annotated[int, Field(ge=0, le=100)] = 10
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800   # recycle connections every 30 min

    # ── Redis / Celery ────────────────────────────────────────────────────
    REDIS_URL: RedisDsn = Field(default="redis://localhost:6379/0")
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # ── Auth ──────────────────────────────────────────────────────────────
    JWT_SECRET: SecretStr = Field(default="change-me-in-production")
    JWT_ALGORITHM: Annotated[str, Field(pattern=r"^HS(256|384|512)$")] = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: Annotated[int, Field(ge=5, le=1440)] = 480   # 8 hours
    REFRESH_TOKEN_EXPIRE_DAYS: Annotated[int, Field(ge=1, le=90)] = 7

    # Super Admin — seeded on startup from env, never hardcoded in source
    SUPER_ADMIN_EMAIL: str = Field(default="admin@sagetl.com")
    SUPER_ADMIN_NAME: str  = Field(default="Super Admin")
    SUPER_ADMIN_PASSWORD: SecretStr = Field(default="Admin@1234")

    # ── Rate limiting ─────────────────────────────────────────────────────
    RATE_LIMIT_DEFAULT: Annotated[int, Field(ge=1)] = 100
    RATE_LIMIT_ADMIN: Annotated[int, Field(ge=1)] = 300

    # ── CORS ──────────────────────────────────────────────────────────────
    CORS_ORIGINS: list[AnyHttpUrl | str] = ["http://localhost:3000"]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    # ── SAP ───────────────────────────────────────────────────────────────
    SAP_BASE_URL: str = "http://103.206.131.27:8081"
    SAP_CLIENT: str = "800"
    SAP_USERNAME: str = ""
    SAP_PASSWORD: SecretStr = Field(default="")
    SAP_TIMEOUT_SECONDS: Annotated[int, Field(ge=5, le=300)] = 120
    # Fallback company code for SAP calls that require one (Service PO validation)
    # when the PO response doesn't carry a COM_CODE of its own.
    SAP_COMPANY_CODE: str = "SSDN"
    # Leading digits of a SAP PO number, used by the fast identity scrape to
    # recognise a PO on the page. Comma-separated; 45 = standard PO.
    SAP_PO_PREFIXES: str = "45,44"

    # ── Ingest pipeline ───────────────────────────────────────────────────
    # Run the fast identity + SAP routing pass alongside OCR on upload.
    PIPELINE_ENABLED: bool = True
    # Hard ceiling on the routing PO lookup, bounding the shared SAP client's
    # exponential-retry backoff: routing has a graceful "SAP unavailable, retry
    # later" path, so it must not stall indefinitely against a dead server.
    # Warm SAP answers in 0.4-0.9 s, but the first call after an idle period
    # costs ~14 s while it wakes up. Routing runs concurrently with the ~17 s OCR
    # pass, so a generous ceiling is free — it only ever delays the outage path,
    # which still finishes before extraction does.
    PIPELINE_SAP_TIMEOUT_SECONDS: Annotated[int, Field(ge=1, le=60)] = 20
    # Routing decides the invoice subtype — there is no manual picker. SAP is
    # authoritative: it reports the line type (ZSER = service) and whether the
    # GR/SES exists, so the user is never asked to classify the document.
    # Set False only to fall back to a user-supplied subtype for debugging.
    PIPELINE_ROUTING_AUTHORITATIVE: bool = True

    # ── Auto-posting ──────────────────────────────────────────────────────
    # Off by default: posting to SAP is irreversible, so removing the human
    # approval step is a financial-control decision, not a technical one.
    AUTO_POST_ENABLED: bool = False
    AUTO_POST_MIN_CONFIDENCE: Annotated[float, Field(ge=0.0, le=1.0)] = 0.85
    # Invoices above this value always require approval. 0 disables the ceiling.
    AUTO_POST_MAX_AMOUNT: float = 100_000.0

    # ── Mail ingestion ────────────────────────────────────────────────────
    # Poll configured mailboxes and ingest invoice attachments automatically.
    MAIL_INGEST_ENABLED: bool = False
    # How many mailboxes are polled at once. One slow or hanging mailbox must
    # not delay every other customer's mail.
    MAIL_POLL_CONCURRENCY: Annotated[int, Field(ge=1, le=32)] = 4
    # Give up on a single mailbox after this long and move on.
    MAIL_POLL_TIMEOUT_SECONDS: Annotated[int, Field(ge=10, le=600)] = 120
    # Most attachments taken from one message, so a single mail cannot flood the
    # pipeline.
    MAIL_MAX_ATTACHMENTS: Annotated[int, Field(ge=1, le=100)] = 20
    # Ignore attachments smaller than this. Kept deliberately low: real invoices
    # are small. Measured across 239 genuine invoices the median is ~5.9 KB and
    # the smallest is 2.3 KB, so an 8 KB floor — which looked reasonable — would
    # have silently discarded 85% of them. Non-PDFs are already excluded by the
    # magic-byte check, so this only needs to catch an empty stub.
    MAIL_MIN_ATTACHMENT_BYTES: Annotated[int, Field(ge=0)] = 1_024

    # ── Google AI (Gemini) ────────────────────────────────────────────────
    GEMINI_API_KEY: SecretStr = Field(default="")
    # Pinned rather than a "-latest" alias: the alias resolves to whatever model
    # is busiest and was returning sustained 503s on PDF payloads while pinned
    # models served the same request fine.
    GEMINI_MODEL: str = "gemini-3.5-flash"

    # ── Storage (S3-compatible) ───────────────────────────────────────────
    S3_BUCKET: str = "docparser-uploads"
    AWS_ACCESS_KEY: str = ""
    AWS_SECRET_KEY: SecretStr = Field(default="")
    AWS_REGION: str = "us-east-1"
    S3_ENDPOINT_URL: str | None = None

    # ── Observability ─────────────────────────────────────────────────────
    SENTRY_DSN: str = ""
    LOG_LEVEL: Annotated[str, Field(pattern=r"^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$")] = "INFO"

    # ── Processing limits ─────────────────────────────────────────────────
    MAX_UPLOAD_SIZE_MB: Annotated[int, Field(ge=1, le=100)] = 50
    PROCESSING_CONCURRENCY: Annotated[int, Field(ge=1, le=20)] = 4

    # ── Derived helpers ───────────────────────────────────────────────────
    @property
    def is_production(self) -> bool:
        return self.ENV == "production"

    @property
    def max_upload_bytes(self) -> int:
        return self.MAX_UPLOAD_SIZE_MB * 1024 * 1024

    @property
    def sync_database_url(self) -> str:
        """Synchronous URL for Alembic migrations (uses psycopg2)."""
        return self.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings: Settings = get_settings()
