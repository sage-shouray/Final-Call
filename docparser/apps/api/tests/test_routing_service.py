"""Routing — the stage that replaced the manual document-type picker.

Each test below corresponds to a defect found by hand in production use, so the
suite is a record of what actually went wrong rather than a guess at what might.
"""
from typing import Any

import pytest

from src.exceptions import SAPConnectionError
from src.schemas.sap import SAPPOResponse
from src.services.routing_service import Route, _sap_answered, classify
from tests.conftest import po_response


class FakeSAP:
    """Stands in for SAPService.fetch_po_details."""

    def __init__(self, result: Any) -> None:
        self._result = result
        self.calls: list[str] = []

    async def fetch_po_details(self, po_number: str) -> SAPPOResponse:
        self.calls.append(po_number)
        if isinstance(self._result, Exception):
            raise self._result
        return SAPPOResponse.model_validate({**self._result, "raw_response": self._result})


@pytest.fixture
def sap(monkeypatch: pytest.MonkeyPatch):
    def _install(result: Any) -> FakeSAP:
        fake = FakeSAP(result)
        import src.services.sap_service as ss
        monkeypatch.setattr(ss, "get_sap_service", lambda *_a, **_k: fake)
        return fake

    return _install


# ── Material vs service ──────────────────────────────────────────────────────

async def test_material_po_with_gr_goes_straight_to_invoice(sap):
    sap(po_response(line_type="NB", gr_number="4900004378"))
    result = await classify(["4500022773"])

    assert result["route"] == Route.MIRO_DIRECT.value
    assert result["invoice_subtype"] == "po"
    assert result["confirmation"]["all_confirmed"] is True


async def test_material_po_without_gr_requires_migo_first(sap):
    """The case that had never run in production until PO 4500022773."""
    sap(po_response(line_type="NB", gr_number=""))
    result = await classify(["4500022773"])

    assert result["route"] == Route.MIGO_THEN_MIRO.value
    assert result["invoice_subtype"] == "po"
    assert result["confirmation"]["missing"] == ["00010"]


async def test_service_po_reads_ses_from_sses_no_not_gr_number(sap):
    """Regression: service lines leave GR_NUMBER empty and carry SSES_NO.

    Reading GR_NUMBER made every service PO look unconfirmed, which blocked
    posting for an entire document class.
    """
    sap(po_response(line_type="ZSER", ses_number="0100000683"))
    result = await classify(["4500022705"])

    assert result["invoice_subtype"] == "service_po"
    assert result["route"] == Route.MIRO_DIRECT.value
    line = result["confirmation"]["lines"][0]
    assert line["kind"] == "SES"
    assert line["documents"] == ["0100000683"]


async def test_service_po_without_ses_is_held_not_sent_to_migo(sap):
    """An SES can only be created in SAP, so this must never route to MIGO."""
    sap(po_response(line_type="ZSER", ses_number=""))
    result = await classify(["4500022705"])

    assert result["route"] == Route.HOLD.value
    assert "service entry sheet" in result["reason"].lower()


async def test_zero_padded_ses_counts_as_absent(sap):
    """SAP pads unset document numbers with zeros rather than leaving them blank."""
    sap(po_response(line_type="ZSER", ses_number="0000000000"))
    result = await classify(["4500022705"])

    assert result["route"] == Route.HOLD.value


# ── No PO / bad PO / SAP down ────────────────────────────────────────────────

async def test_no_po_number_routes_to_fb60(sap):
    sap(po_response())
    result = await classify([])

    assert result["route"] == Route.FB60.value
    assert result["invoice_subtype"] == "non_po"


async def test_rejected_po_is_not_retryable(sap):
    """Regression: SAP answering "Invalid PO / Vendor" as HTTP 500 was being
    reported as an outage with retryable=True, so such documents waited forever
    for a recovery that was never coming."""
    sap(SAPConnectionError('SAP returned HTTP 500: {"MESSAGE":"Invalid PO / Vendor"}'))
    result = await classify(["4510167728"])

    assert result["route"] == Route.HOLD.value
    assert result["retryable"] is False
    assert result["sap_unavailable"] is False
    assert "does not recognise" in result["reason"]


async def test_unreachable_sap_is_retryable(sap):
    """The other half of the same distinction — a real outage must be retryable."""
    sap(SAPConnectionError("All connection attempts failed"))
    result = await classify(["4500022773"])

    assert result["route"] == Route.HOLD.value
    assert result["retryable"] is True
    assert result["sap_unavailable"] is True


@pytest.mark.parametrize(
    ("exc", "answered"),
    [
        (SAPConnectionError('SAP returned HTTP 500: {"MESSAGE":"Invalid PO / Vendor"}'), True),
        (SAPConnectionError("All connection attempts failed"), False),
        (TimeoutError(), False),
    ],
)
def test_sap_answered_discriminator(exc: BaseException, answered: bool):
    assert _sap_answered(exc) is answered


async def test_first_matching_candidate_wins_and_stops(sap):
    """A mis-read PO number should cost one read-only call, not several."""
    fake = sap(po_response(gr_number="4900004378"))
    await classify(["4500022773", "4500099999"])

    assert fake.calls == ["4500022773"]


async def test_multi_line_reports_every_unconfirmed_line(sap):
    sap(po_response(line_type="NB", gr_number="", items=2))
    result = await classify(["4500022773"])

    assert result["confirmation"]["missing"] == ["00010", "00020"]
    assert result["route"] == Route.MIGO_THEN_MIRO.value
