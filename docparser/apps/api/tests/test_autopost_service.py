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
) -> dict[str, Any]:
    return {
        "document_id": "DOC-TEST",
        "extracted": {
            "invoice_no": invoice_no,
            "vendor_gstin": gstin,
            "gross_amount": gross,
            "confidence_score": confidence,
        },
        "pipeline": {
            "routing": {
                "route": route,
                "resolved": route != "hold",
                "vendor_gstin": po_gstin,
                "po_data": {"GROSS_AMOUNT": po_gross},
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
