"""Tenant model — one row per company/client."""
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, _utcnow


class TenantRow(Base):
    __tablename__ = "tenants"

    id:         Mapped[str]      = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name:       Mapped[str]      = mapped_column(String, nullable=False)
    slug:       Mapped[str]      = mapped_column(String, unique=True, nullable=False)
    gstin:      Mapped[str]      = mapped_column(String, nullable=False, default="")
    email:      Mapped[str]      = mapped_column(String, nullable=False, default="")
    phone:      Mapped[str]      = mapped_column(String, nullable=False, default="")
    address:    Mapped[str]      = mapped_column(String, nullable=False, default="")
    status:     Mapped[str]      = mapped_column(String, nullable=False, default="active")
    is_active:  Mapped[bool]     = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, server_default=func.now())

    def to_dict(self) -> dict[str, Any]:
        return {
            "id":         self.id,
            "name":       self.name,
            "slug":       self.slug,
            "gstin":      self.gstin,
            "email":      self.email,
            "phone":      self.phone,
            "address":    self.address,
            "status":     self.status,
            "is_active":  self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else "",
        }


class TenantApiConfigRow(Base):
    __tablename__ = "tenant_api_configs"

    id:               Mapped[str]       = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id:        Mapped[str]       = mapped_column(String, nullable=False)
    api_key:          Mapped[str]       = mapped_column(String, nullable=False)
    label:            Mapped[str]       = mapped_column(String, nullable=False, default="")
    workflow:         Mapped[str]       = mapped_column(String, nullable=False, default="")
    base_url:         Mapped[str]       = mapped_column(String, nullable=False, default="")
    path:             Mapped[str]       = mapped_column(String, nullable=False, default="")
    method:           Mapped[str]       = mapped_column(String, nullable=False, default="POST")
    sap_client:       Mapped[str]       = mapped_column(String, nullable=False, default="800")
    auth_type:        Mapped[str]       = mapped_column(String, nullable=False, default="basic")
    username:         Mapped[str]       = mapped_column(String, nullable=False, default="")
    password:         Mapped[str]       = mapped_column(String, nullable=False, default="")
    extra_headers:    Mapped[dict]      = mapped_column(JSONB, nullable=False, default=dict)
    is_active:        Mapped[bool]      = mapped_column(Boolean, nullable=False, default=True)
    last_tested_at:   Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_test_status: Mapped[str | None]      = mapped_column(String, nullable=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id":               self.id,
            "tenant_id":        self.tenant_id,
            "api_key":          self.api_key,
            "label":            self.label,
            "workflow":         self.workflow,
            "base_url":         self.base_url,
            "path":             self.path,
            "method":           self.method,
            "sap_client":       self.sap_client,
            "auth_type":        self.auth_type,
            "username":         self.username,
            "is_active":        self.is_active,
            "last_tested_at":   self.last_tested_at.isoformat() if self.last_tested_at else None,
            "last_test_status": self.last_test_status,
            "full_url":         f"{self.base_url}/{self.path.lstrip('/')}?sap-client={self.sap_client}",
        }


class PricingConfigRow(Base):
    __tablename__ = "pricing_configs"

    id:                 Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id:          Mapped[str] = mapped_column(String, nullable=False)
    tcode:              Mapped[str] = mapped_column(String, nullable=False)
    label:              Mapped[str] = mapped_column(String, nullable=False, default="")
    price_per_document: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id":                 self.id,
            "tenant_id":          self.tenant_id,
            "tcode":              self.tcode,
            "label":              self.label,
            "price_per_document": float(self.price_per_document),
        }


class BillingRecordRow(Base):
    __tablename__ = "billing_records"

    id:           Mapped[str]   = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id:    Mapped[str]   = mapped_column(String, nullable=False)
    period_month: Mapped[int]   = mapped_column(nullable=False)
    period_year:  Mapped[int]   = mapped_column(nullable=False)
    tcode:        Mapped[str]   = mapped_column(String, nullable=False)
    doc_count:    Mapped[int]   = mapped_column(nullable=False, default=0)
    price_each:   Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    total_amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    status:       Mapped[str]   = mapped_column(String, nullable=False, default="pending")
    created_at:   Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, server_default=func.now())

    def to_dict(self) -> dict[str, Any]:
        return {
            "id":           self.id,
            "tenant_id":    self.tenant_id,
            "period_month": self.period_month,
            "period_year":  self.period_year,
            "tcode":        self.tcode,
            "doc_count":    self.doc_count,
            "price_each":   float(self.price_each),
            "total_amount": float(self.total_amount),
            "status":       self.status,
        }
