"""Resolving which SAP endpoint to call for a given customer.

Each customer runs their own SAP on their own host, so there is no single base
URL. The admin panel records, per customer and per operation, the full endpoint
and optionally the request shape that customer's Z-programs expect; this module
turns (tenant, operation) into a concrete call.

Falls back to the global settings when a customer has no configuration, so a
single-tenant deployment keeps working unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog

from src.config import settings

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class ResolvedEndpoint:
    """Everything needed to make one SAP call for one customer."""

    url:              str
    method:           str = "POST"
    username:         str = ""
    password:         str = ""
    extra_headers:    dict[str, str] = field(default_factory=dict)
    payload_template: dict[str, Any] = field(default_factory=dict)
    api_key:          str = ""
    tenant_id:        str = ""
    # True when this came from the global settings rather than a tenant record.
    is_fallback:      bool = False

    @property
    def auth(self) -> tuple[str, str] | None:
        return (self.username, self.password) if self.username else None

    @property
    def has_template(self) -> bool:
        return bool(self.payload_template)


def _compose_url(row: Any) -> str:
    """Prefer the full URL; fall back to the older base+path+client columns.

    Existing rows were saved before full_url existed, so both forms have to work
    until every customer has been migrated.
    """
    full = (getattr(row, "full_url", "") or "").strip()
    if full:
        return full

    base = (row.base_url or "").strip().rstrip("/")
    path = (row.path or "").strip().lstrip("/")
    if not base or not path:
        return ""
    client = (row.sap_client or "").strip()
    return f"{base}/{path}" + (f"?sap-client={client}" if client else "")


def _fallback(api_key: str, default_path: str) -> ResolvedEndpoint:
    """The single-tenant configuration, for deployments with no tenant records."""
    base = settings.SAP_BASE_URL.rstrip("/")
    url = f"{base}/{default_path.lstrip('/')}"
    if settings.SAP_CLIENT:
        url = f"{url}?sap-client={settings.SAP_CLIENT}"
    return ResolvedEndpoint(
        url=url,
        username=settings.SAP_USERNAME,
        password=settings.SAP_PASSWORD.get_secret_value() if settings.SAP_USERNAME else "",
        api_key=api_key,
        is_fallback=True,
    )


async def resolve(
    api_key: str,
    *,
    tenant_id: str | None,
    default_path: str,
    default_method: str = "POST",
) -> ResolvedEndpoint:
    """Find the endpoint `tenant_id` uses for `api_key`.

    `default_path` is the built-in path, used when the customer has no record —
    so behaviour is unchanged for anyone who has not been configured yet.
    """
    if not tenant_id:
        return _fallback(api_key, default_path)

    from sqlalchemy import select

    from src.database import AsyncSessionLocal
    from src.models.tenant import TenantApiConfigRow

    try:
        async with AsyncSessionLocal() as session:
            row = (await session.execute(
                select(TenantApiConfigRow).where(
                    TenantApiConfigRow.tenant_id == tenant_id,
                    TenantApiConfigRow.api_key == api_key,
                )
            )).scalar_one_or_none()
    except Exception as exc:
        # A configuration lookup must never take down a posting that would
        # otherwise succeed on the default endpoint.
        log.warning("tenant API lookup failed — using defaults",
                    tenant_id=tenant_id, api_key=api_key, error=str(exc))
        return _fallback(api_key, default_path)

    if row is None or not row.is_active:
        return _fallback(api_key, default_path)

    url = _compose_url(row)
    if not url:
        log.warning("tenant endpoint is not configured — using defaults",
                    tenant_id=tenant_id, api_key=api_key)
        return _fallback(api_key, default_path)

    return ResolvedEndpoint(
        url=url,
        method=(row.method or default_method).upper(),
        username=row.username or "",
        password=row.password or "",
        extra_headers=dict(row.extra_headers or {}),
        payload_template=dict(row.payload_template or {}),
        api_key=api_key,
        tenant_id=tenant_id,
    )


async def build_payload(
    endpoint: ResolvedEndpoint,
    context: dict[str, Any],
    *,
    default_payload: dict[str, Any],
    required: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Shape the request body for this customer.

    With no template configured the built-in payload is used unchanged. With one,
    it is rendered from `context` — and a template that fails to supply a field
    named in `required` is rejected rather than sent, because a posting missing
    its PO number is worse than a posting that did not happen.
    """
    if not endpoint.has_template:
        return default_payload

    from src.services.payload_template import render

    rendered, missing = render(endpoint.payload_template, context)
    blocking = [m for m in missing if m in required]
    if blocking:
        raise ValueError(
            f"The configured payload for '{endpoint.api_key}' left required "
            f"field(s) empty: {', '.join(sorted(set(blocking)))}. "
            "Check the sample JSON saved for this company."
        )
    log.info("payload built from tenant template",
             api_key=endpoint.api_key, tenant_id=endpoint.tenant_id,
             unresolved=sorted(set(missing)))
    return rendered
