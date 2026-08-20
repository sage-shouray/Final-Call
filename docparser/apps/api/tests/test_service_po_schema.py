"""ZSPO_VALD/SERV_PO_VAL response handling.

That endpoint validates *and* posts the MIRO in one call, so reading its reply
correctly is what stands between a confirmed posting and a false one.
"""
import pytest

from src.schemas.sap import ServicePOValidationResponse as Resp

SUCCESS = {
    "TOTAL_QTY": 4.0, "TOTAL_NET": 8000.0,
    "CONSUMED_QTY": 1.0, "CONSUMED_NET": 8000.0,
    "AVAILABLE_QTY": 3.0, "AVAILABLE_NET": 0.0,
    "INVOICE_QTY": 1.0, "INVOICE_AMOUNT": 8000.0,
    "VALIDATION_STATUS": "SUCCESS", "VALIDATION_MESSAGE": "Validation Successful",
    "MIRO_STATUS": "SUCCESS", "MIRO_MESSAGE": "MIRO Created Successfully : 5105609711",
    "INVOICE_DOC": "5105609711", "FISCAL_YEAR": 2026,
}


def test_success_reports_both_phases_and_the_document():
    r = Resp.model_validate(SUCCESS)
    assert r.validation_ok is True
    assert r.miro_ok is True
    assert r.succeeded is True
    assert r.miro_number == "5105609711"
    assert r.blocking_reason == ""


def test_validation_passed_but_miro_failed_is_not_a_success():
    """The distinction that matters: SAP can accept the invoice and still not
    create the document. Treating that as posted would record a MIRO number
    that does not exist."""
    r = Resp.model_validate({**SUCCESS, "MIRO_STATUS": "FAILED",
                             "MIRO_MESSAGE": "Terms of payment are incorrect",
                             "INVOICE_DOC": ""})
    assert r.validation_ok is True
    assert r.miro_ok is False
    assert r.succeeded is False
    assert r.blocking_reason == "Terms of payment are incorrect"


def test_failure_reason_comes_from_the_phase_that_failed():
    """Regression: a validation failure was explained with a stale MIRO message."""
    r = Resp.model_validate({**SUCCESS,
                             "VALIDATION_STATUS": "FAILED",
                             "VALIDATION_MESSAGE": "Invoice exceeds available value",
                             "MIRO_STATUS": "", "INVOICE_DOC": ""})
    assert r.blocking_reason == "Invoice exceeds available value"


def test_zero_padded_invoice_doc_is_not_a_document():
    r = Resp.model_validate({**SUCCESS, "INVOICE_DOC": "0000000000"})
    assert r.miro_number == ""
    assert r.succeeded is False


def test_pre_redeploy_field_names_still_parse():
    """Older SAP builds returned STATUS/MESSAGE rather than the split fields."""
    r = Resp.model_validate({"STATUS": "SUCCESS", "MESSAGE": "ok",
                             "MIRO_STATUS": "SUCCESS", "INVOICE_DOC": "5105609711"})
    assert r.validation_ok is True
    assert r.succeeded is True


@pytest.mark.parametrize(
    ("available_net", "expected"),
    [(0.0, "full"), (2000.0, "partial")],
)
def test_consumption_case_reflects_remaining_value(available_net: float, expected: str):
    r = Resp.model_validate({**SUCCESS, "AVAILABLE_NET": available_net})
    assert r.consumption_case == expected


def test_rejected_line_is_never_reported_as_consumed():
    r = Resp.model_validate({**SUCCESS, "VALIDATION_STATUS": "FAILED", "INVOICE_DOC": ""})
    assert r.consumption_case == "rejected"
