"""Mail ingestion.

A mailbox that posts invoices to SAP is an attack surface: the address becomes
known, and anyone can send to it. Most of what follows is about what must *not*
happen — no auto-posting from unknown senders, no double ingestion, no crossing
between tenants.
"""
from datetime import UTC, datetime
from typing import Any

import pytest

from src.services.mail_providers import Attachment, MailMessage, _looks_like_pdf
from src.services.secret_store import decrypt_dict, encrypt_dict
from src.workers.mail_worker import _is_due, _sender_allowed, process_message

PDF = b"%PDF-1.7\n" + b"x" * 20_000


def mailbox(**over: Any) -> dict[str, Any]:
    base = {
        "id": "mb-1", "tenant_id": "tenant-acme", "address": "invoices@acme.com",
        "provider": "imap", "folder": "INBOX", "poll_interval_s": 60,
        "sender_allowlist": [], "auto_post_enabled": False,
        "consecutive_failures": 0, "messages_seen": 0, "documents_ingested": 0,
        "last_polled_at": None,
    }
    return {**base, **over}


def message(**over: Any) -> MailMessage:
    m = MailMessage(
        message_id="<msg-1@vendor.com>", subject="Invoice INV-1",
        sender="ap@vendor.com", received_at=datetime.now(UTC),
        attachments=[Attachment("invoice.pdf", PDF)], provider_id="1",
    )
    for k, v in over.items():
        setattr(m, k, v)
    return m


# ── Sender trust ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    ("sender", "allowlist", "trusted"),
    [
        ("ap@vendor.com",   ["ap@vendor.com"],   True),
        ("AP@Vendor.com",   ["ap@vendor.com"],   True),   # case is not identity
        ("billing@acme.in", ["@acme.in"],        True),   # whole domain
        ("attacker@evil.com", ["@acme.in"],      False),
        ("ap@vendor.com",   [],                  False),  # empty trusts nobody
        ("",                ["@acme.in"],        False),
    ],
)
def test_sender_allowlist(sender: str, allowlist: list[str], trusted: bool):
    assert _sender_allowed(sender, allowlist) is trusted


def test_lookalike_domain_is_not_trusted():
    """'@acme.in' must not match a domain that merely ends with it."""
    assert _sender_allowed("ap@notacme.in", ["@acme.in"]) is False


# ── What reaches the pipeline ────────────────────────────────────────────────

@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch):
    """Capture ingest_document calls instead of writing to the database."""
    calls: list[dict[str, Any]] = []

    async def _fake(**kwargs: Any):
        calls.append(kwargs)
        from src.services.ingestion_service import IngestResult
        return IngestResult(document_id=f"DOC-{len(calls)}", row_id="row")

    import src.services.ingestion_service as ing
    monkeypatch.setattr(ing, "ingest_document", _fake)
    return calls


async def test_attachment_is_ingested_against_the_mailbox_tenant(captured):
    """Tenancy comes from the mailbox, never from the message headers."""
    ids = await process_message(mailbox(), message())

    assert ids == ["DOC-1"]
    assert captured[0]["tenant_id"] == "tenant-acme"
    assert captured[0]["source"].channel == "email"
    assert captured[0]["source"].actor == "ap@vendor.com"


async def test_unknown_sender_is_never_marked_auto_postable(captured):
    """Mail arrives and is processed, but a stranger cannot trigger a posting."""
    await process_message(mailbox(auto_post_enabled=True), message(sender="attacker@evil.com"))

    meta = captured[0]["source"].metadata
    assert meta["sender_trusted"] is False
    assert meta["auto_post_allowed"] is False


async def test_trusted_sender_still_needs_the_mailbox_to_allow_it(captured):
    """Both must agree: a known vendor plus a mailbox configured to automate."""
    await process_message(
        mailbox(sender_allowlist=["ap@vendor.com"], auto_post_enabled=False), message()
    )
    assert captured[0]["source"].metadata["auto_post_allowed"] is False

    captured.clear()
    await process_message(
        mailbox(sender_allowlist=["ap@vendor.com"], auto_post_enabled=True), message()
    )
    assert captured[0]["source"].metadata["auto_post_allowed"] is True


async def test_duplicates_are_reported_not_reingested(captured, monkeypatch):
    """Senders forward and resend; a mailbox re-presents the same attachment."""
    from src.services.ingestion_service import DuplicateDocument

    async def _dup(**kwargs: Any):
        raise DuplicateDocument("DOC-EARLIER")

    import src.services.ingestion_service as ing
    monkeypatch.setattr(ing, "ingest_document", _dup)

    assert await process_message(mailbox(), message()) == []


async def test_tiny_attachments_are_skipped(captured):
    """Signature images and logos arrive on almost every business email."""
    logo = Attachment("signature.pdf", b"%PDF-1.7\n" + b"x" * 100)
    await process_message(mailbox(), message(attachments=[logo]))
    assert captured == []


async def test_one_failing_attachment_does_not_lose_the_others(captured, monkeypatch):
    calls: list[str] = []

    async def _flaky(**kwargs: Any):
        calls.append(kwargs["filename"])
        if kwargs["filename"] == "bad.pdf":
            raise RuntimeError("storage exploded")
        from src.services.ingestion_service import IngestResult
        return IngestResult(document_id="DOC-OK", row_id="row")

    import src.services.ingestion_service as ing
    monkeypatch.setattr(ing, "ingest_document", _flaky)

    ids = await process_message(mailbox(), message(attachments=[
        Attachment("bad.pdf", PDF), Attachment("good.pdf", PDF),
    ]))
    assert ids == ["DOC-OK"]
    assert calls == ["bad.pdf", "good.pdf"]


# ── Attachment recognition ───────────────────────────────────────────────────

@pytest.mark.parametrize(
    ("name", "ctype", "content", "expected"),
    [
        ("inv.pdf", "application/pdf", PDF, True),
        # Many clients label attachments octet-stream; magic bytes decide.
        ("inv.pdf", "application/octet-stream", PDF, True),
        ("inv.PDF", "application/pdf", PDF, True),
        ("logo.png", "image/png", b"\x89PNG\r\n", False),
        ("notes.txt", "text/plain", b"hello", False),
        # Named .pdf but not a PDF — trust the bytes, not the name.
        ("fake.pdf", "text/plain", b"not a pdf at all", False),
    ],
)
def test_pdf_detection(name: str, ctype: str, content: bytes, expected: bool):
    assert _looks_like_pdf(name, ctype, content) is expected


# ── Scheduling ───────────────────────────────────────────────────────────────

def test_a_never_polled_mailbox_is_due():
    assert _is_due(mailbox(), datetime.now(UTC)) is True


def test_a_failing_mailbox_backs_off():
    """A broken configuration should cost one attempt an hour, not one a minute."""
    now = datetime.now(UTC)
    just_polled = now.replace(microsecond=0)

    healthy = mailbox(last_polled_at=just_polled, consecutive_failures=0)
    failing = mailbox(last_polled_at=just_polled, consecutive_failures=8)

    assert _is_due(healthy, now) is False
    assert _is_due(failing, now) is False        # backed off far longer


# ── Credentials ──────────────────────────────────────────────────────────────

def test_credentials_are_opaque_at_rest():
    secret = {"client_secret": "p@ssw0rd-very-secret", "client_id": "abc"}
    blob = encrypt_dict(secret)

    assert "p@ssw0rd-very-secret" not in blob
    assert decrypt_dict(blob) == secret


def test_empty_credentials_round_trip():
    assert decrypt_dict("") == {}


# ── The allowlist must actually gate posting ─────────────────────────────────

@pytest.fixture
def gate_doc():
    def _make(source: str = "email", **meta: Any) -> dict[str, Any]:
        return {
            "document_id": "DOC-TEST",
            "source": source,
            "source_metadata": meta,
            "extracted": {"invoice_no": "INV-1", "vendor_gstin": "27A",
                          "gross_amount": "1000.00", "confidence_score": 1.0},
            "pipeline": {"routing": {
                "route": "miro_direct", "resolved": True, "vendor_gstin": "27A",
                "po_data": {"GROSS_AMOUNT": "1000.00"},
                "confirmation": {"all_confirmed": True, "lines": [], "missing": []},
            }},
        }
    return _make


@pytest.fixture(autouse=True)
def _autopost_env(monkeypatch: pytest.MonkeyPatch):
    from src.config import settings
    from src.services import autopost_service

    async def _no_dup(doc: Any, extracted: Any) -> None:
        return None

    monkeypatch.setattr(autopost_service, "_find_duplicate", _no_dup)
    monkeypatch.setattr(settings, "AUTO_POST_ENABLED", True)
    monkeypatch.setattr(settings, "AUTO_POST_MAX_AMOUNT", 100_000.0)


async def test_email_from_unknown_sender_cannot_auto_post(gate_doc):
    """The security control, end to end: an unrecognised sender is held."""
    from src.services.autopost_service import evaluate

    result = await evaluate(gate_doc(sender_trusted=False, auto_post_allowed=False))
    gate = next(g for g in result["gates"] if g["gate"] == "email_sender_trusted")

    assert gate["passed"] is False
    assert result["auto_post"] is False


async def test_email_from_allowlisted_sender_may_auto_post(gate_doc):
    from src.services.autopost_service import evaluate

    result = await evaluate(gate_doc(sender_trusted=True, auto_post_allowed=True))
    assert result["auto_post"] is True


async def test_web_uploads_are_not_subject_to_the_email_gate(gate_doc):
    """A signed-in user is already authenticated; the gate is for mail only."""
    from src.services.autopost_service import evaluate

    result = await evaluate(gate_doc(source="web"))
    assert not any(g["gate"] == "email_sender_trusted" for g in result["gates"])
    assert result["auto_post"] is True


# ── Deduplication inside the ingestion core ──────────────────────────────────

def test_fingerprint_is_content_addressed():
    from src.services.ingestion_service import file_fingerprint

    assert file_fingerprint(PDF) == file_fingerprint(bytes(PDF))
    assert file_fingerprint(PDF) != file_fingerprint(PDF + b"x")


@pytest.fixture
def ingest_env(monkeypatch: pytest.MonkeyPatch):
    """Run the real ingest_document with storage and the database stubbed out."""
    from src.services import ingestion_service as ing

    state: dict[str, Any] = {"seen": None, "created": []}

    async def _find(fp: str, tid: str | None) -> str | None:
        return state["seen"]

    monkeypatch.setattr(ing, "find_by_fingerprint", _find)

    import src.services.storage_service as store
    monkeypatch.setattr(store, "validate_upload", lambda *a, **k: None)
    monkeypatch.setattr(store, "build_s3_key", lambda *a, **k: "key")

    async def _upload(*a: Any, **k: Any) -> str:
        return "key"

    monkeypatch.setattr(store, "upload_file", _upload)

    class Repo:
        def __init__(self, session: Any) -> None: ...
        async def create(self, data: dict[str, Any]) -> str:
            state["created"].append(data)
            return "row-1"
        async def find_by_id(self, _: str) -> None:
            return None
        async def update(self, *a: Any, **k: Any) -> None: ...
        async def update_status(self, *a: Any, **k: Any) -> None: ...

    from contextlib import asynccontextmanager

    class Session:
        async def commit(self) -> None: ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

    @asynccontextmanager
    async def _sess():
        yield Session()

    import src.database
    import src.repositories.document_repository as dr
    monkeypatch.setattr(src.database, "AsyncSessionLocal", _sess)
    monkeypatch.setattr(dr, "DocumentRepository", Repo)
    return state


async def test_reingesting_the_same_bytes_is_refused_for_mail(ingest_env):
    """The mail path sets reject_duplicates: a mailbox re-presenting the same
    attachment must not create a second document, or the invoice gets paid twice."""
    from src.services.ingestion_service import DuplicateDocument, ingest_document

    ingest_env["seen"] = "DOC-EARLIER"

    with pytest.raises(DuplicateDocument) as exc:
        await ingest_document(
            file_bytes=PDF, filename="invoice.pdf",
            tenant_id="tenant-acme", reject_duplicates=True, start_pipeline=False,
        )
    assert exc.value.document_id == "DOC-EARLIER"
    assert ingest_env["created"] == []


async def test_a_person_may_re_upload_the_same_file(ingest_env):
    """The web path reports the earlier copy rather than refusing — a human
    re-uploading has intent, and the duplicate gate catches it before posting."""
    from src.services.ingestion_service import ingest_document

    ingest_env["seen"] = "DOC-EARLIER"
    result = await ingest_document(
        file_bytes=PDF, filename="invoice.pdf",
        tenant_id="tenant-acme", reject_duplicates=False, start_pipeline=False,
    )
    assert result.duplicate_of == "DOC-EARLIER"
    assert len(ingest_env["created"]) == 1


async def test_the_fingerprint_is_stored_for_later_lookups(ingest_env):
    from src.services.ingestion_service import file_fingerprint, ingest_document

    await ingest_document(
        file_bytes=PDF, filename="invoice.pdf",
        tenant_id="tenant-acme", start_pipeline=False,
    )
    assert ingest_env["created"][0]["file"]["fingerprint"] == file_fingerprint(PDF)


async def test_the_document_is_stored_against_the_supplied_tenant(ingest_env):
    """The field the entire multi-tenant model rests on.

    With email there is no signed-in user to fall back on, so if this is not
    written correctly a customer's invoice lands unowned — and an unowned
    document is visible to every tenant.
    """
    from src.services.ingestion_service import ingest_document

    await ingest_document(
        file_bytes=PDF, filename="invoice.pdf",
        tenant_id="tenant-acme", start_pipeline=False,
    )
    assert ingest_env["created"][0]["tenant_id"] == "tenant-acme"


async def test_email_ingest_records_its_origin(ingest_env):
    from src.services.ingestion_service import IngestSource, ingest_document

    await ingest_document(
        file_bytes=PDF, filename="invoice.pdf", tenant_id="tenant-acme",
        source=IngestSource(channel="email", actor="ap@vendor.com",
                            reference="<msg-1@vendor.com>"),
        start_pipeline=False,
    )
    row = ingest_env["created"][0]
    assert row["source"] == "email"
    assert row["uploaded_by"] == "ap@vendor.com"
    assert row["source_reference"] == "<msg-1@vendor.com>"


# ── What the sender is told ──────────────────────────────────────────────────

def _doc(**over: Any) -> dict[str, Any]:
    base = {
        "extracted": {"invoice_no": "INV-4500022773"},
        "pipeline": {"routing": {"po_number": "4500022773"}, "autopost": {"gates": []}},
        "miro_posting": {}, "grn_posting": {},
    }
    return {**base, **over}


def test_a_posted_invoice_quotes_its_sap_documents():
    """The numbers a vendor will quote back at you later."""
    from src.services.mail_reply import compose_reply

    subject, body = compose_reply(_doc(
        miro_posting={"status": "success", "miro_number": "5105609733"},
        grn_posting={"status": "success", "grn_number": "4900004378"},
    ))
    assert "Posted" in subject
    assert "5105609733" in body
    assert "4900004378" in body


def test_a_held_invoice_explains_why():
    from src.services.mail_reply import compose_reply

    subject, body = compose_reply(_doc(pipeline={"routing": {
        "route": "hold",
        "reason": "SAP does not recognise PO number 4510167689 — check the PO number.",
    }}))
    assert "Needs attention" in subject
    assert "4510167689" in body


def test_a_transient_failure_asks_for_nothing():
    """No point telling a vendor to act on an outage at our end."""
    from src.services.mail_reply import compose_reply

    _, body = compose_reply(_doc(pipeline={"routing": {
        "route": "hold", "reason": "Could not reach SAP.", "retryable": True,
    }}))
    assert "no action is needed" in body.lower()


def test_an_invoice_awaiting_review_lists_the_reasons():
    from src.services.mail_reply import compose_reply

    subject, body = compose_reply(_doc(pipeline={
        "routing": {"route": "miro_direct"},
        "autopost": {"gates": [
            {"gate": "within_auto_post_ceiling", "passed": False,
             "detail": "Invoice 702,100.00 exceeds the auto-post ceiling."},
            {"gate": "vendor_match", "passed": True, "detail": "ok"},
        ]},
    }))
    assert "Received" in subject
    assert "702,100.00" in body
    assert "ok" not in body          # passing checks are not the sender's problem


async def test_web_uploads_are_never_replied_to():
    """There is nobody to reply to — the document came from a browser."""
    from src.services import mail_reply

    async def _find(_: str) -> dict[str, Any]:
        return {"source": "web", "uploaded_by": "user-123"}

    class Repo:
        def __init__(self, s: Any) -> None: ...
        find_by_document_id = staticmethod(_find)

    import src.repositories.document_repository as dr
    original = dr.DocumentRepository
    dr.DocumentRepository = Repo  # type: ignore[misc]
    try:
        assert await mail_reply.send_outcome("DOC-1") is False
    finally:
        dr.DocumentRepository = original  # type: ignore[misc]


# ── The size floor must not eat real invoices ────────────────────────────────

def test_the_attachment_floor_admits_a_realistically_small_invoice():
    """Regression: the floor was set to 8 KB by guesswork.

    Measured across 239 real invoices the median is ~5.9 KB and the smallest
    2.3 KB, so that floor silently discarded 85% of genuine mail — the worst
    possible failure, because nothing appears to go wrong.
    """
    from src.config import settings

    smallest_real_invoice = 2_359
    assert settings.MAIL_MIN_ATTACHMENT_BYTES < smallest_real_invoice


async def test_a_small_but_genuine_invoice_is_ingested(captured):
    """A 3 KB single-page PDF is an ordinary invoice, not a signature image."""
    small = Attachment("invoice.pdf", b"%PDF-1.7\n" + b"x" * 3_000)
    ids = await process_message(mailbox(), message(attachments=[small]))
    assert ids == ["DOC-1"]
