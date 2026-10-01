"""Telling the sender what happened to their invoice.

Without this, emailing an invoice is shouting into a void: the sender has no
idea whether it posted, is waiting for review, or was rejected — so they phone
Accounts Payable, which is the cost the automation was meant to remove.

Replies are plain text and deliberately brief. They quote SAP's own document
number when there is one, because that is what a vendor will reference later.
"""
from __future__ import annotations

from typing import Any

import structlog

log = structlog.get_logger(__name__)


def compose_reply(document: dict[str, Any]) -> tuple[str, str]:
    """Return (subject, body) describing where this document got to."""
    extracted = document.get("extracted") or {}
    pipeline = document.get("pipeline") or {}
    routing = pipeline.get("routing") or {}
    autopost = pipeline.get("autopost") or {}
    miro = document.get("miro_posting") or {}
    grn = document.get("grn_posting") or {}

    invoice_no = extracted.get("invoice_no") or "your invoice"
    po_number = routing.get("po_number") or extracted.get("po_number") or ""

    # Posted — the only outcome that needs no follow-up.
    if miro.get("status") == "success" and miro.get("miro_number"):
        lines = [f"{invoice_no} has been posted."]
        if grn.get("status") == "success" and grn.get("grn_number"):
            lines.append(f"Goods receipt: {grn['grn_number']}")
        lines.append(f"Invoice document: {miro['miro_number']}")
        if po_number:
            lines.append(f"Purchase order: {po_number}")
        return (f"Posted: {invoice_no}", "\n".join(lines))

    # Held because SAP could not place it — the sender can usually fix this.
    if routing.get("route") == "hold":
        reason = routing.get("reason") or "This invoice needs review before it can be posted."
        body = [f"{invoice_no} could not be processed automatically.", "", reason]
        if routing.get("retryable"):
            body.append("")
            body.append("This looks temporary — no action is needed; it will be retried.")
        return (f"Needs attention: {invoice_no}", "\n".join(body))

    # Received and correct, but waiting on a person.
    failed = [g for g in (autopost.get("gates") or []) if not g.get("passed")]
    if failed:
        body = [f"{invoice_no} has been received and is awaiting review.", ""]
        body += [f"- {g.get('detail', g.get('gate', ''))}" for g in failed]
        return (f"Received: {invoice_no}", "\n".join(body))

    return (
        f"Received: {invoice_no}",
        f"{invoice_no} has been received and is being processed.",
    )


async def send_outcome(document_id: str) -> bool:
    """Reply to whoever emailed this document. Returns True if a reply was sent.

    Only replies to documents that arrived by email, and only through the
    mailbox that received them — so the vendor sees an answer from the address
    they wrote to.
    """
    from sqlalchemy import select

    from src.database import AsyncSessionLocal
    from src.models.mailbox import MailboxRow
    from src.repositories.document_repository import DocumentRepository

    async with AsyncSessionLocal() as session:
        document = await DocumentRepository(session).find_by_document_id(document_id)
    if not document:
        return False
    if (document.get("source") or "web") != "email":
        return False

    meta = document.get("source_metadata") or {}
    recipient = document.get("uploaded_by") or ""
    mailbox_address = meta.get("mailbox") or ""
    if not recipient or "@" not in recipient:
        return False

    async with AsyncSessionLocal() as session:
        mailbox = (await session.execute(
            select(MailboxRow).where(
                MailboxRow.address == mailbox_address,
                MailboxRow.tenant_id == (document.get("tenant_id") or ""),
            )
        )).scalar_one_or_none()
    if not mailbox:
        return False

    subject, body = compose_reply(document)

    from src.services.mail_providers import GraphProvider
    from src.services.secret_store import decrypt_dict

    # Only Graph can send today. IMAP is read-only here: replying would need SMTP
    # credentials, which are a separate thing to ask a customer for.
    from src.models.mailbox import MailProvider
    if mailbox.provider != MailProvider.MICROSOFT_GRAPH.value:
        log.info("reply skipped — provider cannot send",
                 provider=mailbox.provider, document_id=document_id)
        return False

    try:
        credentials = decrypt_dict(mailbox.credentials_enc)
        provider = GraphProvider(credentials, mailbox.address, mailbox.folder)
        await _graph_send(provider, recipient, subject, body)
        log.info("outcome replied", document_id=document_id, to=recipient)
        return True
    except Exception as exc:
        # A failed reply must never affect the document itself.
        log.warning("could not send outcome reply", document_id=document_id, error=str(exc))
        return False


async def _graph_send(provider: Any, to: str, subject: str, body: str) -> None:
    import httpx

    token = await provider._access_token()   # noqa: SLF001 — same package
    payload = {
        "message": {
            "subject": subject,
            "body": {"contentType": "Text", "content": body},
            "toRecipients": [{"emailAddress": {"address": to}}],
        },
        "saveToSentItems": True,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"https://graph.microsoft.com/v1.0/users/{provider._mailbox}/sendMail",  # noqa: SLF001
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
        )
    if resp.status_code >= 400:
        raise RuntimeError(f"Graph sendMail returned {resp.status_code}: {resp.text[:160]}")
