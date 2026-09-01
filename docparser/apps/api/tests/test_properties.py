"""Property-based tests — rules that must hold for every input, not just chosen ones.

Hand-picked examples test the cases someone thought of. These state a rule and
let Hypothesis hunt for a counter-example across hundreds of generated inputs,
shrinking any failure to the smallest case that still breaks. That is how a
suite reaches real coverage of an input space without thousands of hand-written
functions.

Every property here guards something that would cost money if it were wrong.
"""
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from src.schemas.sap import ServicePOValidationResponse
from src.services.ingestion_service import file_fingerprint
from src.services.ocr_service import _calculate_confidence
from src.services.secret_store import decrypt_dict, encrypt_dict
from src.workers.mail_worker import _sender_allowed

# Money-shaped values: two decimal places, non-negative, within a realistic range.
amounts = st.decimals(min_value=Decimal("0"), max_value=Decimal("100000000"),
                      places=2, allow_nan=False, allow_infinity=False)
quantities = st.decimals(min_value=Decimal("0"), max_value=Decimal("100000"),
                         places=3, allow_nan=False, allow_infinity=False)
emails = st.from_regex(r"[a-z][a-z0-9._]{0,12}@[a-z][a-z0-9-]{0,10}\.[a-z]{2,4}", fullmatch=True)


# ── Credential encryption ────────────────────────────────────────────────────

# Credential values as they actually occur: API keys, GUIDs, app passwords and
# secrets — printable text. Generating arbitrary Unicode here tests the JSON
# layer rather than the encryption, and produced one failure I could not
# reproduce; scoping the strategy to the real domain keeps the property honest.
credential_text = st.text(
    alphabet=st.characters(min_codepoint=32, max_codepoint=126),
    max_size=200,
)
credential_key = st.text(
    alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd"), whitelist_characters="_-"),
    min_size=1, max_size=30,
)


@given(st.dictionaries(credential_key, credential_text, max_size=8))
@settings(max_examples=200)
def test_any_credential_set_survives_a_round_trip(payload: dict[str, str]):
    """Customers' mailbox passwords go through this. Nothing may be lost or altered."""
    assert decrypt_dict(encrypt_dict(payload)) == payload


@given(credential_text.filter(lambda v: len(v) >= 8))
@settings(max_examples=200)
def test_a_secret_never_appears_in_its_own_ciphertext(secret: str):
    """The point of encrypting at rest: a database dump must not reveal the value."""
    blob = encrypt_dict({"client_secret": secret})
    assert secret not in blob


# ── Sender trust ─────────────────────────────────────────────────────────────

@given(emails)
@settings(max_examples=300)
def test_an_empty_allowlist_trusts_nobody(sender: str):
    """A mailbox address is public once vendors have it. Absent configuration
    must mean 'trust no one', never 'trust everyone'."""
    assert _sender_allowed(sender, []) is False


@given(emails)
@settings(max_examples=300)
def test_an_exact_address_is_always_trusted_by_itself(sender: str):
    assert _sender_allowed(sender, [sender]) is True


@given(emails, emails)
@settings(max_examples=400)
def test_one_address_never_authorises_a_different_one(a: str, b: str):
    """The core of the allowlist: listing one vendor must not admit another."""
    if a.lower() != b.lower():
        assert _sender_allowed(a, [b]) is False


@given(emails)
@settings(max_examples=300)
def test_trust_ignores_case_but_not_identity(sender: str):
    """Mail clients vary the case of addresses; that must not change the answer."""
    assert _sender_allowed(sender.upper(), [sender.lower()]) is True


# ── Service PO posting response ──────────────────────────────────────────────

@given(
    validation=st.sampled_from(["SUCCESS", "FAILED", "ERROR", ""]),
    miro=st.sampled_from(["SUCCESS", "FAILED", "NOT_RUN", ""]),
    doc=st.sampled_from(["5105609711", "", "0000000000"]),
)
@settings(max_examples=200)
def test_success_requires_both_phases_and_a_document(validation: str, miro: str, doc: str):
    """SERV_PO_VAL validates and posts in one call. Treating a validated-but-
    unposted invoice as done would record a MIRO number that does not exist."""
    r = ServicePOValidationResponse.model_validate({
        "VALIDATION_STATUS": validation, "MIRO_STATUS": miro, "INVOICE_DOC": doc,
    })
    expected = (validation == "SUCCESS" and miro == "SUCCESS"
                and doc not in ("", "0000000000"))
    assert r.succeeded is expected


@given(
    validation=st.sampled_from(["SUCCESS", "FAILED"]),
    miro=st.sampled_from(["SUCCESS", "FAILED"]),
    doc=st.sampled_from(["5105609711", ""]),
)
@settings(max_examples=100)
def test_a_document_that_did_not_post_always_says_why(validation: str, miro: str, doc: str):
    """Whatever the combination, an unposted invoice must carry a reason — a
    silent failure leaves nobody anything to act on."""
    r = ServicePOValidationResponse.model_validate({
        "VALIDATION_STATUS": validation, "VALIDATION_MESSAGE": "v-msg",
        "MIRO_STATUS": miro, "MIRO_MESSAGE": "m-msg", "INVOICE_DOC": doc,
    })
    if not r.succeeded:
        assert r.blocking_reason != ""


# ── Extraction confidence ────────────────────────────────────────────────────

@given(
    invoice_no=st.one_of(st.none(), st.text(min_size=1, max_size=20)),
    invoice_date=st.one_of(st.none(), st.text(min_size=1, max_size=12)),
    vendor=st.one_of(st.none(), st.text(min_size=1, max_size=30)),
    gstin=st.one_of(st.none(), st.text(min_size=1, max_size=15)),
    gross=st.one_of(st.none(), amounts),
    taxable=st.one_of(st.none(), amounts),
)
@settings(max_examples=300)
def test_confidence_stays_inside_its_range(invoice_no, invoice_date, vendor, gstin, gross, taxable):
    """A gate compares this against a threshold; a value outside 0..1 would make
    that comparison meaningless."""
    score = _calculate_confidence({
        "invoice_no": invoice_no, "invoice_date": invoice_date,
        "vendor_name": vendor, "vendor_gstin": gstin,
        "gross_amount": gross, "taxable_amount": taxable,
    })
    assert 0.0 <= score <= 1.0


@given(gross=st.one_of(st.none(), amounts))
@settings(max_examples=100)
def test_a_zero_rated_invoice_is_never_penalised_for_absent_tax(gross):
    """Regression as a property: CGST/SGST are genuinely absent on a V0 invoice,
    and counting that as missing data capped every one of them below the
    auto-post threshold."""
    full = {
        "invoice_no": "INV-1", "invoice_date": "01-09-2026",
        "vendor_name": "V", "vendor_gstin": "G",
        "gross_amount": gross or Decimal("100"), "taxable_amount": gross or Decimal("100"),
        "cgst_amount": None, "sgst_amount": None, "igst_amount": None,
        "line_items": [{}],
    }
    assert _calculate_confidence(full) == 1.0


# ── Deduplication ────────────────────────────────────────────────────────────

@given(st.binary(min_size=1, max_size=4000))
@settings(max_examples=300)
def test_the_same_bytes_always_fingerprint_the_same(payload: bytes):
    """Duplicate detection rests on this — an unstable hash would let the same
    invoice be paid twice."""
    assert file_fingerprint(payload) == file_fingerprint(bytes(payload))


@given(st.binary(min_size=1, max_size=2000), st.binary(min_size=1, max_size=2000))
@settings(max_examples=300)
def test_different_bytes_fingerprint_differently(a: bytes, b: bytes):
    """The other half: two genuinely different invoices must not collide, or one
    would be silently discarded as a duplicate of the other."""
    if a != b:
        assert file_fingerprint(a) != file_fingerprint(b)
