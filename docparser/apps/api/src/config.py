"""Application configuration via pydantic-settings."""
# config reload marker: gemini-2.5-flash
from functools import lru_cache
from typing import Annotated

from pydantic import (
    AnyHttpUrl,
    Field,
    RedisDsn,
    SecretStr,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # ── App ───────────────────────────────────────────────────────────────
    APP_VERSION: str = "0.1.0"
    ENV: Annotated[str, Field(pattern=r"^(development|staging|production)$")] = "development"
    DEBUG: bool = False
    SECRET_KEY: SecretStr = Field(default="change-me-in-production")

    # ── Database ──────────────────────────────────────────────────────────
    MONGODB_URL: str = Field(default="mongodb://localhost:27017")
    MONGODB_DB_NAME: str = "docparser"
    MONGODB_MAX_POOL_SIZE: Annotated[int, Field(ge=1, le=200)] = 50
    MONGODB_MIN_POOL_SIZE: Annotated[int, Field(ge=0, le=50)] = 5
    MONGODB_CONNECT_TIMEOUT_MS: int = 5_000
    MONGODB_SERVER_SELECTION_TIMEOUT_MS: int = 10_000

    @model_validator(mode="after")
    def _pool_bounds(self) -> "Settings":
        if self.MONGODB_MIN_POOL_SIZE > self.MONGODB_MAX_POOL_SIZE:
            raise ValueError("MONGODB_MIN_POOL_SIZE must be ≤ MONGODB_MAX_POOL_SIZE")
        return self

    # ── Redis / Celery ────────────────────────────────────────────────────
    REDIS_URL: RedisDsn = Field(default="redis://localhost:6379/0")
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # ── Auth ──────────────────────────────────────────────────────────────
    JWT_SECRET: SecretStr = Field(default="change-me-in-production")
    JWT_ALGORITHM: Annotated[str, Field(pattern=r"^HS(256|384|512)$")] = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: Annotated[int, Field(ge=5, le=1440)] = 480   # 8 hours
    REFRESH_TOKEN_EXPIRE_DAYS: Annotated[int, Field(ge=1, le=90)] = 7

    # ── Rate limiting ─────────────────────────────────────────────────────
    RATE_LIMIT_DEFAULT: Annotated[int, Field(ge=1)] = 100   # req / min, regular users
    RATE_LIMIT_ADMIN: Annotated[int, Field(ge=1)] = 300     # req / min, admin role

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

    # ── Google AI (Gemini) ────────────────────────────────────────────────
    GEMINI_API_KEY: SecretStr = Field(default="")
    GEMINI_MODEL: str = "gemini-2.5-flash"

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

    # ── Derived helpers (not env vars) ────────────────────────────────────
    @property
    def is_production(self) -> bool:
        return self.ENV == "production"

    @property
    def max_upload_bytes(self) -> int:
        return self.MAX_UPLOAD_SIZE_MB * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings: Settings = get_settings()
