"""Auto-post gating.

These gates are the only thing standing between an extraction mistake and an
unattended posting, so each one is tested for both the pass and the fail, and
the overall decision is tested for "any failure blocks".
"""
from typing import Any

import pytest

from src.services import autopost_service
from src.services.autopost_service import evaluate


def make_doc(
    *,
    route: str = "miro_direct",
    confirmed: bool = True,
    invoice_no: str = "INV-1",
    gstin: str = "09AAACC1206D2ZJ",
    po_gstin: str = "09AAACC1206D2ZJ",
    gross: str = "1000.00",
    po_gross: str = "1000.00",
    confidence: float = 1.0,
    taxable: str | None = None,
    po_net: str | None = None,
) -> dict[str, Any]:
    """A document that passes every gate unless an argument is changed.

    `taxable` and `po_net` default to the respective gross figures, which makes
    the default document zero-rated on both sides — tax rates agree at 0% and
    the tax gate passes without competing with the tests about value and route.
    Override either one to create the tax discrepancy the gate exists to catch.
    """
    return {
        "document_id": "DOC-TEST",
        "extracted": {
            "invoice_no": invoice_no,
            "vendor_gstin": gstin,
            "gross_amount": gross,
            "taxable_amount": gross if taxable is None else taxable,
            "confidence_score": confidence,
        },
        "pipeline": {
            "routing": {
                "route": route,
                "resolved": route != "hold",
                "vendor_gstin": po_gstin,
                "po_data": {
                    "GROSS_AMOUNT": po_gross,
                    "NET_AMOUNT": po_gross if po_net is None else po_net,
                },
                "confirmation": {"all_confirmed": confirmed, "lines": [], "missing": []},
            }
        },
    }


def gate(result: dict[str, Any], name: str) -> dict[str, Any]:
    return next(g for g in result["gates"] if g["gate"] == name)


@pytest.fixture(autouse=True)
def no_duplicates(monkeypatch: pytest.MonkeyPatch):
    """Duplicate lookup hits the database; default it to "not a duplicate" so
    each test exercises the gate it is actually about."""
    async def _none(doc: Any, extracted: Any) -> None:
        return None
    monkeypatch.setattr(autopost_service, "_find_duplicate", _none)


@pytest.fixture
def auto_on(monkeypatch: pytest.MonkeyPatch):
    from src.config import settings
    monkeypatch.setattr(settings, "AUTO_POST_ENABLED", True)
    monkeypatch.setattr(settings, "AUTO_POST_MAX_AMOUNT", 100_000.0)
    monkeypatch.setattr(settings, "AUTO_POST_MIN_CONFIDENCE", 0.85)


# ── The gate that blocked its own route ──────────────────────────────────────

async def test_migo_then_miro_is_not_blocked_by_its_missing_gr(auto_on):
    """Regression: a missing GR was treated as a blocker on the very route whose
    purpose is to post that GR, so no such document could ever auto-post."""
    result = await evaluate(make_doc(route="migo_then_miro", confirmed=False))

    assert gate(result, "receipt_confirmed")["passed"] is True
    assert result["auto_post"] is True


async def test_miro_direct_still_requires_a_confirmed_receipt(auto_on):
    """The other side: if the route claims the GR is already there, its absence
    is a genuine contradiction and must block."""
    result = await evaluate(make_doc(route="miro_direct", confirmed=False))

    assert gate(result, "receipt_confirmed")["passed"] is False
    assert result["auto_post"] is False


async def test_non_po_needs_no_receipt(auto_on):
    result = await evaluate(make_doc(route="fb60", confirmed=False))
    assert gate(result, "receipt_confirmed")["passed"] is True


# ── The individual gates ─────────────────────────────────────────────────────

async def test_low_confidence_blocks(auto_on):
    result = await evaluate(make_doc(confidence=0.5))
    assert gate(result, "extraction_confidence")["passed"] is False
    assert result["auto_post"] is False


async def test_vendor_mismatch_blocks(auto_on):
    result = await evaluate(make_doc(gstin="09AAACC1206D2ZJ", po_gstin="27ZZZZZ0000Z1Z1"))
    assert gate(result, "vendor_match")["passed"] is False


async def test_invoice_above_po_value_blocks(auto_on):
    result = await evaluate(make_doc(gross="2000.00", po_gross="1000.00"))
    assert gate(result, "within_po_value")["passed"] is False


async def test_invoice_below_po_value_is_allowed(auto_on):
    """A partial invoice is normal, not an error."""
    result = await evaluate(make_doc(gross="400.00", po_gross="1000.00"))
    assert gate(result, "within_po_value")["passed"] is True


async def test_value_ceiling_blocks_large_invoices(auto_on):
    result = await evaluate(make_doc(gross="702100.00", po_gross="702100.00"))
    assert gate(result, "within_auto_post_ceiling")["passed"] is False
    assert result["auto_post"] is False


async def test_held_route_blocks(auto_on):
    result = await evaluate(make_doc(route="hold"))
    assert gate(result, "route_resolved")["passed"] is False


async def test_duplicate_invoice_blocks(auto_on, monkeypatch: pytest.MonkeyPatch):
    async def _dup(doc: Any, extracted: Any) -> str:
        return "DOC-2026-706516"
    monkeypatch.setattr(autopost_service, "_find_duplicate", _dup)

    result = await evaluate(make_doc())
    assert gate(result, "not_duplicate")["passed"] is False
    assert "DOC-2026-706516" in gate(result, "not_duplicate")["detail"]


# ── The overall decision ─────────────────────────────────────────────────────

async def test_all_gates_passing_permits_auto_post(auto_on):
    result = await evaluate(make_doc())
    assert all(g["passed"] for g in result["gates"])
    assert result["auto_post"] is True
    assert result["decision"] == "auto_post"


async def test_disabled_flag_overrides_a_perfect_document(monkeypatch: pytest.MonkeyPatch):
    """The kill switch must win regardless of how clean the document is.

    The flag is pinned rather than left to the ambient config: this test used to
    pass only because auto-posting happened to be off by default, and started
    failing the moment it was enabled in .env — which is the wrong reason for a
    unit test to change colour.
    """
    from src.config import settings
    monkeypatch.setattr(settings, "AUTO_POST_ENABLED", False)

    result = await evaluate(make_doc())
    assert all(g["passed"] for g in result["gates"])
    assert result["auto_post"] is False
    assert result["decision"] == "manual_approval_required"


# ── No value limit ───────────────────────────────────────────────────────────

async def test_a_ceiling_of_zero_lets_any_amount_post(monkeypatch: pytest.MonkeyPatch):
    """0 turns the value limit off: the remaining gates carry the whole burden."""
    from src.config import settings

    monkeypatch.setattr(settings, "AUTO_POST_ENABLED", True)
    monkeypatch.setattr(settings, "AUTO_POST_MIN_CONFIDENCE", 0.85)
    monkeypatch.setattr(settings, "AUTO_POST_MAX_AMOUNT", 0.0)

    result = await evaluate(make_doc(gross="702100.00", po_gross="702100.00"))

    assert gate(result, "within_auto_post_ceiling")["passed"] is True
    assert "No value limit" in gate(result, "within_auto_post_ceiling")["detail"]
    assert result["auto_post"] is True


async def test_removing_the_ceiling_does_not_weaken_the_other_gates(monkeypatch: pytest.MonkeyPatch):
    """A large invoice may now post, but only if it is otherwise correct."""
    from src.config import settings

    monkeypatch.setattr(settings, "AUTO_POST_ENABLED", True)
    monkeypatch.setattr(settings, "AUTO_POST_MAX_AMOUNT", 0.0)
    monkeypatch.setattr(settings, "AUTO_POST_MIN_CONFIDENCE", 0.85)

    # Same large amount, but the invoice exceeds what the PO authorises.
    result = await evaluate(make_doc(gross="999999.00", po_gross="702100.00"))
    assert result["auto_post"] is False
    assert gate(result, "within_po_value")["passed"] is False


# ── Tax treatment (the gap DOC-2026-620099 fell through) ─────────────────────

async def test_an_exempt_invoice_against_a_taxable_po_is_held(auto_on):
    """Regression, from a real document. PO 4500022798 ordered 10 units at 100
    with tax code R1 (18%), gross 1,180. The invoice matched on quantity and
    unit price but claimed "Exempt (No Tax)", gross 1,000.

    The value gate is a ceiling, so 1,000 <= 1,180 passed and the whole document
    was cleared to post — carrying a 180.00 tax difference into SAP. Quantity and
    price agreeing is exactly what makes this one easy to miss.
    """
    doc = make_doc(taxable="1000.00", gross="1000.00",
                   po_net="1000.00", po_gross="1180.00")
    result = await evaluate(doc)

    assert gate(result, "within_po_value")["passed"] is True,         "1,000 is genuinely under the 1,180 ceiling — that gate was never wrong"
    assert gate(result, "tax_matches_po")["passed"] is False
    assert "tax, not quantity or price" in gate(result, "tax_matches_po")["detail"]
    assert result["auto_post"] is False


async def test_a_partial_delivery_at_the_same_tax_code_still_posts(auto_on):
    """The reason the gate compares rates and not amounts: a half shipment
    invoices half the value, which must not read as a tax discrepancy."""
    doc = make_doc(taxable="300.00", gross="354.00",
                   po_net="1000.00", po_gross="1180.00")
    result = await evaluate(doc)

    assert gate(result, "tax_matches_po")["passed"] is True
    assert result["auto_post"] is True


async def test_a_vendor_overcharging_tax_is_held(auto_on):
    """The other direction — 28% billed against an 18% PO."""
    doc = make_doc(taxable="1000.00", gross="1280.00",
                   po_net="1000.00", po_gross="1180.00")
    result = await evaluate(doc)
    assert gate(result, "tax_matches_po")["passed"] is False


async def test_an_undeterminable_tax_rate_is_held_not_skipped(auto_on):
    """This module's rule is that a gate which cannot be evaluated fails. An
    invoice with no taxable value gives nothing to compare, and defaulting that
    to "fine" would quietly reopen the hole."""
    doc = make_doc(taxable="0", gross="1180.00",
                   po_net="1000.00", po_gross="1180.00")
    result = await evaluate(doc)
    assert gate(result, "tax_matches_po")["passed"] is False
    assert "Cannot determine" in gate(result, "tax_matches_po")["detail"]


async def test_a_non_po_invoice_has_no_tax_code_to_match(auto_on):
    """FB60 has no PO behind it, so there is nothing to disagree with."""
    result = await evaluate(make_doc(route="fb60"))
    assert gate(result, "tax_matches_po")["passed"] is True


# ── The prohibition: data that disagrees with SAP may never post ─────────────

async def test_a_tax_mismatch_blocks_manual_posting_too():
    """The hole PO 4500022798 exposed. The gates governed unattended posting
    only, so a reviewer clicking Post skipped every one of them and sent an
    invoice SAP had already contradicted straight to the ledger.

    No auto_on fixture here on purpose: this must hold whether or not
    unattended posting is switched on, because it is a fact about the data.
    """
    from src.services.autopost_service import blocking_failures

    doc = make_doc(taxable="1000.00", gross="1000.00",
                   po_net="1000.00", po_gross="1180.00")
    failures = await blocking_failures(doc)

    assert [f["gate"] for f in failures] == ["tax_matches_po"]
    assert "the difference is tax" in failures[0]["detail"]


async def test_a_reviewer_may_still_override_a_poor_extraction():
    """The other half of the rule. Low confidence is a judgement about reading
    the invoice, and reading it is exactly what the reviewer just did — so it
    must not become an un-overridable block, or review means nothing."""
    from src.services.autopost_service import blocking_failures

    doc = make_doc(confidence=0.10)
    assert await blocking_failures(doc) == []


async def test_a_wrong_vendor_can_never_be_approved():
    from src.services.autopost_service import blocking_failures

    doc = make_doc(gstin="09AAACC1206D2ZJ", po_gstin="27ZZZZZ9999Z1ZZ")
    assert [f["gate"] for f in await blocking_failures(doc)] == ["vendor_match"]


async def test_an_invoice_above_the_po_can_never_be_approved():
    from src.services.autopost_service import blocking_failures

    doc = make_doc(gross="5000.00", taxable="5000.00",
                   po_gross="1000.00", po_net="1000.00")
    assert "within_po_value" in [f["gate"] for f in await blocking_failures(doc)]


async def test_a_document_that_agrees_with_sap_is_not_blocked():
    from src.services.autopost_service import blocking_failures

    assert await blocking_failures(make_doc()) == []
