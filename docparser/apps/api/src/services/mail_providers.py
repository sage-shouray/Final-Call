"""Reading invoice mail, from Microsoft 365 or any IMAP server.

One interface, two implementations, because customers do not all use the same
mail host. Everything downstream — deduplication, routing, gating, posting — is
identical whichever provider delivered the bytes; only the fetch differs.

Microsoft is the more involved of the two and the one most customers need:
Exchange Online no longer accepts a username and password for IMAP, so Graph
with an app-only token is the supported route. The Azure application should be
restricted to the single invoice mailbox with New-ApplicationAccessPolicy,
otherwise Mail.Read as an application permission reads the whole tenant.
"""
from __future__ import annotations

import asyncio
import email
import email.policy
import imaplib
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
import structlog

log = structlog.get_logger(__name__)

_GRAPH = "https://graph.microsoft.com/v1.0"
_PDF_TYPES = {"application/pdf", "application/x-pdf", "application/octet-stream"}


class MailAuthError(RuntimeError):
    """Credentials were rejected — a human must fix the configuration."""


class MailTransientError(RuntimeError):
    """The mailbox could not be reached; worth retrying on the next cycle."""


@dataclass(slots=True)
class Attachment:
    filename: str
    content: bytes
    content_type: str = "application/pdf"


@dataclass(slots=True)
class MailMessage:
    message_id: str
    subject: str
    sender: str
    received_at: datetime | None = None
    attachments: list[Attachment] = field(default_factory=list)
    provider_id: str = ""      # id used to mark the message read
    raw_headers: dict[str, Any] = field(default_factory=dict)


def _looks_like_pdf(filename: str, content_type: str, content: bytes) -> bool:
    """Accept a PDF however the sender's mail client labelled it.

    Many clients send application/octet-stream, so the magic bytes are the
    reliable test; the extension alone is not.
    """
    if content[:5] == b"%PDF-":
        return True
    return filename.lower().endswith(".pdf") and content_type.lower() in _PDF_TYPES


class MailProviderBase:
    """What every provider must offer."""

    async def test_connection(self) -> dict[str, Any]:
        raise NotImplementedError

    async def fetch_unread(self, limit: int = 25) -> list[MailMessage]:
        raise NotImplementedError

    async def mark_read(self, message: MailMessage) -> None:
        raise NotImplementedError


# ── Microsoft 365 ────────────────────────────────────────────────────────────


class GraphProvider(MailProviderBase):
    """Microsoft Graph, app-only (client credentials).

    No user signs in, so nothing breaks when a person leaves or a password
    changes. The client secret does expire, which is the failure this reports
    most clearly, since otherwise ingestion simply stops on an arbitrary date.
    """

    def __init__(self, credentials: dict[str, Any], mailbox: str, folder: str = "Inbox") -> None:
        self._tenant = str(credentials.get("tenant_id") or "").strip()
        self._client_id = str(credentials.get("client_id") or "").strip()
        self._secret = str(credentials.get("client_secret") or "").strip()
        self._mailbox = mailbox.strip()
        self._folder = folder or "Inbox"
        self._token: str = ""
        self._token_expires_at: float = 0.0

    async def _access_token(self) -> str:
        # Tokens last about an hour; re-use with a minute of headroom rather
        # than paying for a round trip on every poll.
        if self._token and time.time() < self._token_expires_at - 60:
            return self._token

        if not (self._tenant and self._client_id and self._secret):
            raise MailAuthError("Microsoft credentials incomplete — need tenant_id, client_id and client_secret.")

        url = f"https://login.microsoftonline.com/{self._tenant}/oauth2/v2.0/token"
        form = {
            "client_id": self._client_id,
            "client_secret": self._secret,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials",
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, data=form)
        if resp.status_code != 200:
            detail = ""
            try:
                body = resp.json()
                detail = body.get("error_description") or body.get("error") or ""
            except Exception:
                detail = resp.text[:200]
            if "AADSTS7000222" in detail or "expired" in detail.lower():
                raise MailAuthError(f"The Azure client secret has expired. {detail[:160]}")
            raise MailAuthError(f"Microsoft rejected the credentials: {detail[:200]}")

        payload = resp.json()
        self._token = payload["access_token"]
        self._token_expires_at = time.time() + int(payload.get("expires_in", 3600))
        return self._token

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        token = await self._access_token()
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(f"{_GRAPH}{path}",
                                    headers={"Authorization": f"Bearer {token}"},
                                    params=params)
        if resp.status_code == 403:
            raise MailAuthError(
                "Graph returned 403. Grant Mail.Read as an *application* permission "
                "with admin consent, and check the ApplicationAccessPolicy covers this mailbox."
            )
        if resp.status_code == 404:
            raise MailAuthError(f"Mailbox or folder not found: {self._mailbox} / {self._folder}")
        if resp.status_code == 429:
            raise MailTransientError("Graph is throttling this application; retrying later.")
        if resp.status_code >= 400:
            raise MailTransientError(f"Graph returned HTTP {resp.status_code}: {resp.text[:160]}")
        return resp.json()

    async def test_connection(self) -> dict[str, Any]:
        data = await self._get(f"/users/{self._mailbox}/mailFolders/{self._folder}")
        return {
            "ok": True,
            "mailbox": self._mailbox,
            "folder": data.get("displayName", self._folder),
            "unread": data.get("unreadItemCount", 0),
            "total": data.get("totalItemCount", 0),
        }

    async def fetch_unread(self, limit: int = 25) -> list[MailMessage]:
        data = await self._get(
            f"/users/{self._mailbox}/mailFolders/{self._folder}/messages",
            params={
                "$filter": "isRead eq false and hasAttachments eq true",
                "$select": "id,subject,from,receivedDateTime,internetMessageId",
                "$top": str(limit),
                "$orderby": "receivedDateTime asc",
            },
        )
        messages: list[MailMessage] = []
        for item in data.get("value", []):
            sender = (((item.get("from") or {}).get("emailAddress")) or {}).get("address", "")
            received = item.get("receivedDateTime")
            msg = MailMessage(
                message_id=item.get("internetMessageId") or item.get("id", ""),
                subject=item.get("subject") or "",
                sender=(sender or "").lower(),
                received_at=(
                    datetime.fromisoformat(received.replace("Z", "+00:00")) if received else None
                ),
                provider_id=item.get("id", ""),
            )
            msg.attachments = await self._attachments(msg.provider_id)
            messages.append(msg)
        return messages

    async def _attachments(self, message_id: str) -> list[Attachment]:
        import base64

        data = await self._get(f"/users/{self._mailbox}/messages/{message_id}/attachments")
        out: list[Attachment] = []
        for att in data.get("value", []):
            if att.get("@odata.type") != "#microsoft.graph.fileAttachment":
                continue          # skip item attachments and inline references
            if att.get("isInline"):
                continue          # signature images and logos
            raw = att.get("contentBytes")
            if not raw:
                continue
            content = base64.b64decode(raw)
            name = att.get("name") or "attachment"
            ctype = att.get("contentType") or "application/octet-stream"
            if _looks_like_pdf(name, ctype, content):
                out.append(Attachment(filename=name, content=content, content_type="application/pdf"))
        return out

    async def mark_read(self, message: MailMessage) -> None:
        token = await self._access_token()
        async with httpx.AsyncClient(timeout=30) as client:
            await client.patch(
                f"{_GRAPH}/users/{self._mailbox}/messages/{message.provider_id}",
                headers={"Authorization": f"Bearer {token}"},
                json={"isRead": True},
            )


# ── IMAP ─────────────────────────────────────────────────────────────────────


class ImapProvider(MailProviderBase):
    """Any IMAP server, including Gmail with an app password.

    imaplib is synchronous, so each operation runs in a worker thread to keep
    the event loop free — a stalled mail server must not freeze the API.
    """

    def __init__(self, credentials: dict[str, Any], mailbox: str, folder: str = "INBOX") -> None:
        self._host = str(credentials.get("host") or "").strip()
        self._port = int(credentials.get("port") or 993)
        self._username = str(credentials.get("username") or mailbox).strip()
        self._password = str(credentials.get("password") or "")
        self._folder = folder or "INBOX"
        self._mailbox = mailbox

    def _connect(self) -> imaplib.IMAP4_SSL:
        if not (self._host and self._username and self._password):
            raise MailAuthError("IMAP credentials incomplete — need host, username and password.")
        try:
            conn = imaplib.IMAP4_SSL(self._host, self._port)
        except OSError as exc:
            raise MailTransientError(f"Could not reach {self._host}:{self._port} — {exc}") from exc
        try:
            conn.login(self._username, self._password)
        except imaplib.IMAP4.error as exc:
            text = str(exc)
            # Exchange Online refuses password auth outright; say so plainly
            # rather than letting someone re-check a correct password.
            if "AUTHENTICATE" in text.upper() or "disabled" in text.lower():
                raise MailAuthError(
                    "The server refused password authentication. Microsoft 365 has "
                    "disabled Basic Auth for IMAP — use the Microsoft Graph provider instead. "
                    f"({text[:120]})"
                ) from exc
            raise MailAuthError(f"Login rejected: {text[:160]}") from exc
        return conn

    def _fetch_sync(self, limit: int) -> list[MailMessage]:
        conn = self._connect()
        try:
            conn.select(self._folder)
            status, data = conn.search(None, "UNSEEN")
            if status != "OK":
                return []
            ids = (data[0].split() or [])[:limit]
            messages: list[MailMessage] = []
            for num in ids:
                # BODY.PEEK leaves the message unread — it is only marked once
                # its attachments have actually been ingested.
                status, payload = conn.fetch(num, "(BODY.PEEK[])")
                if status != "OK" or not payload or not payload[0]:
                    continue
                parsed = email.message_from_bytes(payload[0][1], policy=email.policy.default)
                messages.append(self._to_message(parsed, num.decode()))
            return messages
        finally:
            try:
                conn.close()
            except Exception:
                pass
            conn.logout()

    def _to_message(self, parsed: Any, provider_id: str) -> MailMessage:
        from email.utils import parseaddr, parsedate_to_datetime

        _, sender = parseaddr(parsed.get("From", ""))
        received = None
        if parsed.get("Date"):
            try:
                received = parsedate_to_datetime(parsed["Date"])
            except Exception:
                received = None

        attachments: list[Attachment] = []
        for part in parsed.walk():
            if part.get_content_maintype() == "multipart":
                continue
            if part.get_content_disposition() not in ("attachment", "inline"):
                continue
            name = part.get_filename() or "attachment"
            content = part.get_payload(decode=True) or b""
            ctype = part.get_content_type()
            if content and _looks_like_pdf(name, ctype, content):
                attachments.append(Attachment(filename=name, content=content, content_type="application/pdf"))

        return MailMessage(
            message_id=parsed.get("Message-ID", "") or f"imap-{provider_id}",
            subject=parsed.get("Subject", "") or "",
            sender=(sender or "").lower(),
            received_at=received,
            attachments=attachments,
            provider_id=provider_id,
        )

    async def test_connection(self) -> dict[str, Any]:
        def _probe() -> dict[str, Any]:
            conn = self._connect()
            try:
                status, data = conn.select(self._folder, readonly=True)
                if status != "OK":
                    raise MailAuthError(f"Folder not found: {self._folder}")
                total = int(data[0]) if data and data[0] else 0
                status, unseen = conn.search(None, "UNSEEN")
                pending = len(unseen[0].split()) if status == "OK" and unseen[0] else 0
                return {"ok": True, "mailbox": self._mailbox, "folder": self._folder,
                        "total": total, "unread": pending}
            finally:
                try:
                    conn.close()
                except Exception:
                    pass
                conn.logout()

        return await asyncio.to_thread(_probe)

    async def fetch_unread(self, limit: int = 25) -> list[MailMessage]:
        return await asyncio.to_thread(self._fetch_sync, limit)

    async def mark_read(self, message: MailMessage) -> None:
        def _mark() -> None:
            conn = self._connect()
            try:
                conn.select(self._folder)
                conn.store(message.provider_id, "+FLAGS", "\\Seen")
            finally:
                try:
                    conn.close()
                except Exception:
                    pass
                conn.logout()

        await asyncio.to_thread(_mark)


# ── Factory ──────────────────────────────────────────────────────────────────


def build_provider(provider: str, credentials: dict[str, Any], address: str,
                   folder: str = "") -> MailProviderBase:
    from src.models.mailbox import MailProvider

    if provider == MailProvider.MICROSOFT_GRAPH.value:
        return GraphProvider(credentials, address, folder or "Inbox")
    if provider == MailProvider.GMAIL_IMAP.value:
        creds = {"host": "imap.gmail.com", "port": 993,
                 "username": credentials.get("username") or address,
                 "password": credentials.get("password") or credentials.get("app_password", "")}
        return ImapProvider(creds, address, folder or "INBOX")
    if provider == MailProvider.IMAP.value:
        return ImapProvider(credentials, address, folder or "INBOX")
    raise ValueError(f"Unknown mail provider: {provider}")
