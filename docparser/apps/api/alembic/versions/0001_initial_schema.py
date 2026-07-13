"""Initial PostgreSQL schema — documents, users, audit_logs, customers.

Revision ID: 0001
Revises:
Create Date: 2026-07-09
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable pgcrypto for gen_random_uuid()
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # ------------------------------------------------------------------
    # documents
    # ------------------------------------------------------------------
    op.create_table(
        "documents",
        sa.Column("id", sa.String(), primary_key=True, server_default=sa.text("gen_random_uuid()::varchar")),
        sa.Column("document_id", sa.String(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("tcode", sa.String(), nullable=False),
        sa.Column("invoice_subtype", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="uploaded"),
        sa.Column("uploaded_by", sa.String(), nullable=False, server_default=""),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("file", JSONB(), nullable=False, server_default="{}"),
        sa.Column("extracted", JSONB(), nullable=True),
        sa.Column("sap_validation", JSONB(), nullable=True),
        sa.Column("grn_posting", JSONB(), nullable=True),
        sa.Column("miro_posting", JSONB(), nullable=True),
        sa.Column("fb60_posting", JSONB(), nullable=True),
        sa.Column("so_simulation", JSONB(), nullable=True),
        sa.Column("so_posting", JSONB(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_log", JSONB(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_documents_document_id", "documents", ["document_id"], unique=True)
    op.create_index("ix_documents_status", "documents", ["status"])
    op.create_index("ix_documents_type", "documents", ["type"])
    op.create_index("ix_documents_tcode", "documents", ["tcode"])
    op.create_index("ix_documents_uploaded_at", "documents", ["uploaded_at"])
    op.create_index("ix_documents_uploaded_by", "documents", ["uploaded_by"])
    op.create_index("ix_documents_status_uploaded_at", "documents", ["status", "uploaded_at"])

    # ------------------------------------------------------------------
    # users
    # ------------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column("id", sa.String(), primary_key=True, server_default=sa.text("gen_random_uuid()::varchar")),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("hashed_password", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False, server_default="operator"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("last_login", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_role", "users", ["role"])

    # ------------------------------------------------------------------
    # audit_logs
    # ------------------------------------------------------------------
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(), primary_key=True, server_default=sa.text("gen_random_uuid()::varchar")),
        sa.Column("document_id", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("performed_by", sa.String(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("details", JSONB(), nullable=False, server_default="{}"),
        sa.Column("ip_address", sa.String(), nullable=False, server_default=""),
    )
    op.create_index("ix_audit_logs_document_id", "audit_logs", ["document_id"])
    op.create_index("ix_audit_logs_timestamp", "audit_logs", ["timestamp"])
    op.create_index("ix_audit_logs_document_timestamp", "audit_logs", ["document_id", "timestamp"])

    # ------------------------------------------------------------------
    # customers
    # ------------------------------------------------------------------
    op.create_table(
        "customers",
        sa.Column("id", sa.String(), primary_key=True, server_default=sa.text("gen_random_uuid()::varchar")),
        sa.Column("customer_id", sa.String(), nullable=False),
        sa.Column("data", JSONB(), nullable=False, server_default="{}"),
    )
    op.create_index("ix_customers_customer_id", "customers", ["customer_id"], unique=True)
    op.execute("""
        CREATE INDEX ix_customers_fts ON customers
        USING GIN (to_tsvector('english',
            coalesce(data->>'CUSTOMER_NAME','') || ' ' ||
            coalesce(data->>'CITY','') || ' ' ||
            coalesce(customer_id,'')
        ))
    """)


def downgrade() -> None:
    op.drop_table("customers")
    op.drop_table("audit_logs")
    op.drop_table("users")
    op.drop_table("documents")
