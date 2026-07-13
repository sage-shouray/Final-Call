"""Alembic environment — uses SQLAlchemy sync engine for migrations."""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Load app config and all ORM models so Alembic sees the metadata
from src.config import settings
from src.models.base import Base
import src.models.document   # noqa: F401 — registers DocumentRow
import src.models.user       # noqa: F401 — registers UserRow
import src.models.audit_log  # noqa: F401 — registers AuditLogRow

config = context.config

# Wire up alembic's logging from the .ini file
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Override sqlalchemy.url with the psycopg2 sync URL from our settings
config.set_main_option("sqlalchemy.url", settings.sync_database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
