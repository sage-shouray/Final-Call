"""Admin endpoints for per-tenant invoice mailboxes.

Credentials are write-only: an administrator can set them and test them, but the
API never returns them. Support staff need to know a mailbox is configured and
healthy, not what the password is.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

import structlog
from fastapi import APIRouter
from sqlalchemy import select

from src.database import AsyncSessionLocal
from src.exceptions import NotFoundError, ValidationError
from src.middleware.auth import CurrentUser, require_role
from src.models.mailbox import MailboxRow, MailProvider, SeenMessageRow
from src.services.secret_store import decrypt_dict, encrypt_dict
from src.utils.serializer import serialize_doc

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/admin/companies/{tenant_id}/mailboxes", tags=["Mailboxes"])

# What each provider needs, used to reject a half-filled form before it is saved
# and to tell the administrator exactly which field is missing.
_REQUIRED: dict[str, tuple[str, ...]] = {
    MailProvider.MICROSOFT_GRAPH.value: ("tenant_id", "client_id", "client_secret"),
    MailProvider.IMAP.value:            ("host", "username", "password"),
    MailProvider.GMAIL_IMAP.value:      ("password",),
}


def _require_admin(user: CurrentUser) -> None:
    if user.role != "admin":
        raise ValidationError("Administrator access required.", error_code="PERMISSION_DENIED")


@router.get("")
async def list_mailboxes(tenant_id: str, current_user: CurrentUser) -> list[dict[str, Any]]:
    _require_admin(current_user)
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(MailboxRow).where(MailboxRow.tenant_id == tenant_id)
        )).scalars().all()
    return [serialize_doc(r.to_dict()) for r in rows]


@router.post("", status_code=201)
async def create_mailbox(
    tenant_id: str,
    body: dict[str, Any],
    current_user: CurrentUser,
    _role: Annotated[Any, require_role("admin")] = None,
) -> dict[str, Any]:
    _require_admin(current_user)

    provider = str(body.get("provider") or MailProvider.IMAP.value).strip()
    if provider not in _REQUIRED:
        raise ValidationError(
            f"Unknown provider '{provider}'. Allowed: {list(_REQUIRED)}",
            error_code="UNKNOWN_PROVIDER",
        )

    address = str(body.get("address") or "").strip()
    if not address:
        raise ValidationError("A mailbox address is required.", error_code="MISSING_ADDRESS")

    # Credentials may be filled in later. Registering the address first is the
    # normal case: the Azure app registration needs a Global Admin and often
    # arrives days after someone decides which mailbox to use. A mailbox without
    # them simply cannot be enabled — enforced below and on update.
    credentials = body.get("credentials") or {}
    if credentials:
        missing = [f for f in _REQUIRED[provider] if not str(credentials.get(f) or "").strip()]
        if missing:
            raise ValidationError(
                f"Missing credential field(s) for {provider}: {', '.join(missing)}",
                error_code="INCOMPLETE_CREDENTIALS",
            )

    row = MailboxRow(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        provider=provider,
        label=str(body.get("label") or address),
        address=address,
        credentials_enc=encrypt_dict(credentials) if credentials else "",
        folder=str(body.get("folder") or ("Inbox" if provider == MailProvider.MICROSOFT_GRAPH.value else "INBOX")),
        poll_interval_s=int(body.get("poll_interval_s") or 60),
        # Disabled until someone has run Test Connection successfully — a
        # mailbox that starts polling on save fails silently in the log.
        enabled=False,
        sender_allowlist=list(body.get("sender_allowlist") or []),
        auto_post_enabled=bool(body.get("auto_post_enabled", False)),
    )
    async with AsyncSessionLocal() as session:
        session.add(row)
        await session.commit()
        await session.refresh(row)
    log.info("mailbox created", tenant_id=tenant_id, address=address, provider=provider)
    return serialize_doc(row.to_dict())


@router.put("/{mailbox_id}")
async def update_mailbox(
    tenant_id: str,
    mailbox_id: str,
    body: dict[str, Any],
    current_user: CurrentUser,
    _role: Annotated[Any, require_role("admin")] = None,
) -> dict[str, Any]:
    _require_admin(current_user)
    async with AsyncSessionLocal() as session:
        row = (await session.execute(
            select(MailboxRow).where(
                MailboxRow.id == mailbox_id, MailboxRow.tenant_id == tenant_id
            )
        )).scalar_one_or_none()
        if not row:
            raise NotFoundError("Mailbox not found", error_code="MAILBOX_NOT_FOUND")

        for field in ("label", "address", "folder"):
            if field in body:
                setattr(row, field, str(body[field] or ""))
        if "poll_interval_s" in body:
            row.poll_interval_s = max(15, int(body["poll_interval_s"] or 60))
        if "sender_allowlist" in body:
            row.sender_allowlist = list(body["sender_allowlist"] or [])
        if "auto_post_enabled" in body:
            row.auto_post_enabled = bool(body["auto_post_enabled"])
        if "enabled" in body:
            if body["enabled"] and not row.credentials_enc:
                raise ValidationError(
                    "Add credentials before enabling this mailbox.",
                    error_code="CREDENTIALS_REQUIRED",
                )
            row.enabled = bool(body["enabled"])
            if row.enabled:
                # Give a re-enabled mailbox a clean slate so backoff does not
                # keep it idle after the configuration has been corrected.
                row.consecutive_failures = 0
                row.last_error = ""
        # Credentials are replaced wholesale or left alone; a partial update
        # would silently mix old and new secrets.
        if body.get("credentials"):
            row.credentials_enc = encrypt_dict(body["credentials"])

        await session.commit()
        await session.refresh(row)
    return serialize_doc(row.to_dict())


@router.delete("/{mailbox_id}", status_code=204)
async def delete_mailbox(
    tenant_id: str,
    mailbox_id: str,
    current_user: CurrentUser,
    _role: Annotated[Any, require_role("admin")] = None,
) -> None:
    _require_admin(current_user)
    async with AsyncSessionLocal() as session:
        row = (await session.execute(
            select(MailboxRow).where(
                MailboxRow.id == mailbox_id, MailboxRow.tenant_id == tenant_id
            )
        )).scalar_one_or_none()
        if row:
            await session.delete(row)
            await session.commit()


@router.post("/{mailbox_id}/test")
async def test_mailbox(
    tenant_id: str,
    mailbox_id: str,
    current_user: CurrentUser,
    _role: Annotated[Any, require_role("admin")] = None,
) -> dict[str, Any]:
    """Try the stored credentials and report what came back.

    Read-only: it counts messages and never ingests, so an administrator can
    verify a configuration without processing anything.
    """
    _require_admin(current_user)
    from src.services.mail_providers import MailAuthError, build_provider

    async with AsyncSessionLocal() as session:
        row = (await session.execute(
            select(MailboxRow).where(
                MailboxRow.id == mailbox_id, MailboxRow.tenant_id == tenant_id
            )
        )).scalar_one_or_none()
        if not row:
            raise NotFoundError("Mailbox not found", error_code="MAILBOX_NOT_FOUND")
        if not row.credentials_enc:
            return {"ok": False, "kind": "config",
                    "error": "No credentials saved for this mailbox yet."}
        provider_name, address, folder = row.provider, row.address, row.folder
        credentials = decrypt_dict(row.credentials_enc)

    try:
        provider = build_provider(provider_name, credentials, address, folder)
        result = await provider.test_connection()
        async with AsyncSessionLocal() as session:
            fresh = (await session.execute(
                select(MailboxRow).where(MailboxRow.id == mailbox_id)
            )).scalar_one()
            fresh.last_error = ""
            fresh.consecutive_failures = 0
            fresh.last_success_at = datetime.now(UTC)
            await session.commit()
        return {"ok": True, **result}
    except MailAuthError as exc:
        return {"ok": False, "error": str(exc), "kind": "auth"}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "kind": "connection"}


@router.get("/{mailbox_id}/messages")
async def recent_messages(
    tenant_id: str,
    mailbox_id: str,
    current_user: CurrentUser,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """What arrived and what became of it — the inbox view for support."""
    _require_admin(current_user)
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(SeenMessageRow)
            .where(SeenMessageRow.mailbox_id == mailbox_id)
            .order_by(SeenMessageRow.processed_at.desc())
            .limit(min(limit, 200))
        )).scalars().all()
    return [serialize_doc({
        "message_id":   r.message_id,
        "subject":      r.subject,
        "sender":       r.sender,
        "received_at":  r.received_at,
        "outcome":      r.outcome,
        "document_ids": r.document_ids or [],
        "processed_at": r.processed_at,
    }) for r in rows]
