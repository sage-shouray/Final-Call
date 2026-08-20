"""Gross vs net on Service PO lines.

An Indian GST invoice line carries three figures: taxable (net), tax, and amount
(gross). SAP carries NET_AMOUNT and GROSS_AMOUNT. Mixing the two families makes
a correct invoice look like an overrun by exactly the tax, which blocked every
taxed service invoice from posting.
"""
from typing import Any

import pytest

from src.schemas.sap import SAPPOResponse
from src.services.validation_service import check_service_po_ceilings
from tests.conftest import po_response


def sap_line(net: str, gross: str) -> SAPPOResponse:
    raw = po_response(line_type="ZSER", ses_number="0100000683", ordered="1", net_amount=net)
    raw["PO_LINE_ITEMS"][0]["GROSS_AMOUNT"] = gross
    raw["PO_LINE_ITEMS"][0]["NET_AMOUNT"] = net
    return SAPPOResponse.model_validate({**raw, "raw_response": raw})


def invoice(quantity: str = "1", taxable: str = "7000.0", amount: str = "8260.0") -> dict[str, Any]:
    return {"line_items": [{
        "line_number": "00010", "quantity": quantity,
        "taxable_amount": taxable, "tax_amount": "1260.0", "amount": amount,
    }]}


def test_gross_line_against_gross_po_is_within_limit():
    """Regression: 8,260 gross vs 7,000 net was reported as a 1,260 overrun on a
    line where the two figures in fact agree."""
    result = check_service_po_ceilings(invoice(), sap_line(net="7000.00", gross="8260.00"))

    assert result["all_within_po"] is True
    assert result["violations"] == []


def test_genuine_overrun_is_still_caught():
    """The fix must not simply widen the ceiling by the tax amount."""
    result = check_service_po_ceilings(
        invoice(taxable="9000.0", amount="10620.0"),
        sap_line(net="7000.00", gross="8260.00"),
    )

    assert result["all_within_po"] is False
    assert result["violations"][0]["field"] == "line[00010].amount"


def test_falls_back_to_net_when_po_has_no_gross():
    """Not every PO line carries GROSS_AMOUNT; the check must still work."""
    raw = po_response(line_type="ZSER", ses_number="0100000683", ordered="1", net_amount="7000.00")
    raw["PO_LINE_ITEMS"][0]["GROSS_AMOUNT"] = ""
    po = SAPPOResponse.model_validate({**raw, "raw_response": raw})

    result = check_service_po_ceilings(invoice(taxable="7000.0", amount="7000.0"), po)
    assert result["all_within_po"] is True


def test_quantity_overrun_is_independent_of_amounts():
    result = check_service_po_ceilings(invoice(quantity="5"), sap_line("7000.00", "8260.00"))

    assert result["all_within_po"] is False
    assert result["violations"][0]["field"] == "line[00010].quantity"


@pytest.mark.parametrize(
    ("taxable", "amount", "expected"),
    [("7000.0", "8260.0", 7000.0), ("0", "8260.0", 8260.0)],
)
async def test_serv_po_val_is_sent_the_taxable_amount(monkeypatch, taxable, amount, expected):
    """SERV_PO_VAL nets invoice_amount against AVAILABLE_NET, so it must receive
    the line's taxable value — falling back to gross only when taxable is absent.
    """
    from src.schemas.sap import ServicePOValidationResponse
    from src.services import validation_service

    sent: dict[str, Any] = {}

    class FakeSAP:
        async def post_service_po_line(self, **kwargs: Any) -> ServicePOValidationResponse:
            sent.update(kwargs)
            return ServicePOValidationResponse.model_validate({
                "VALIDATION_STATUS": "SUCCESS", "MIRO_STATUS": "SUCCESS",
                "INVOICE_DOC": "5105609711", "AVAILABLE_NET": 0.0,
            })

    import src.services.sap_service as ss
    monkeypatch.setattr(ss, "get_sap_service", lambda: FakeSAP())

    extracted = {"line_items": [{
        "line_number": "00010", "quantity": "1",
        "taxable_amount": taxable, "amount": amount,
    }]}
    await validation_service.post_service_po_lines(extracted, "4500022705", "SSDN")

    assert sent["invoice_amount"] == expected


# ── Extraction confidence ────────────────────────────────────────────────────

def test_zero_rated_invoice_is_not_penalised_for_absent_tax():
    """Regression: a correctly-read V0 invoice scored 0.80 because CGST/SGST were
    null — capping every zero-rated invoice below the auto-post threshold."""
    from src.services.ocr_service import _calculate_confidence

    invoice = {
        "invoice_no": "INV-1", "invoice_date": "20-08-2026",
        "vendor_name": "Asian Paints", "vendor_gstin": "06AAACC1206D2ZJ",
        "gross_amount": 8000, "taxable_amount": 8000,
        "cgst_amount": None, "sgst_amount": None,
        "line_items": [{}],
    }
    assert _calculate_confidence(invoice) == 1.0


def test_taxed_invoice_still_expects_its_tax_fields():
    from src.services.ocr_service import _calculate_confidence

    invoice = {
        "invoice_no": "INV-1", "invoice_date": "20-08-2026",
        "vendor_name": "V", "vendor_gstin": "G",
        "gross_amount": 8260, "taxable_amount": 7000,
        "tax_amount": 1260, "cgst_amount": None, "sgst_amount": None, "igst_amount": None,
        "line_items": [{}],
    }
    assert _calculate_confidence(invoice) < 1.0


def test_genuinely_missing_header_data_still_scores_low():
    from src.services.ocr_service import _calculate_confidence

    assert _calculate_confidence({"vendor_name": "V", "gross_amount": 1}) < 0.6
