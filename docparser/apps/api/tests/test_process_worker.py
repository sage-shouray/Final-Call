"""Route execution — GR then invoice, in one action.

A posted goods receipt is real stock movement and a posted MIRO is a real
liability. Neither can be repeated, so most of what follows is about what must
*not* happen on a retry.
"""
from contextlib import asynccontextmanager
from typing import Any

import pytest

from src.workers.process_worker import ProcessBlocked, run_process_direct

OK_GRN = {"status": "success", "grn_number": "4900004378"}
OK_MIRO = {"status": "success", "miro_number": "5105609733"}
BAD_GRN = {"status": "failed", "grn_number": "", "message": "GR rejected by SAP"}
BAD_MIRO = {"status": "failed", "miro_number": ""}


def make_doc(
    route: str,
    *,
    grn: dict | None = None,
    miro: dict | None = None,
    validation: dict | None = None,
) -> dict[str, Any]:
    return {
        "id": "row-1",
        "document_id": "DOC-TEST",
        "status": "validated",
        "pipeline": {"routing": {"route": route, "reason": "test"}},
        "grn_posting": grn,
        "miro_posting": miro,
        "sap_validation": validation if validation is not None else {"is_valid": True},
    }


class Harness:
    """Records which posting steps ran, and lets each one set its outcome."""

    def __init__(self, doc: dict[str, Any], grn_result=None, miro_result=None) -> None:
        self.doc = dict(doc)
        self.calls: list[str] = []
        self._grn = grn_result
        self._miro = miro_result

    async def migo(self, document_id: str, posted_by: str = "system") -> None:
        self.calls.append("MIGO")
        if self._grn is not None:
            self.doc = dict(self.doc, grn_posting=self._grn)

    async def miro(self, document_id: str, posted_by: str = "system") -> None:
        self.calls.append("MIRO")
        if self._miro is not None:
            self.doc = dict(self.doc, miro_posting=self._miro)

    async def validate(self, document_id: str) -> None:
        self.calls.append("VALIDATE")


@pytest.fixture
def run(monkeypatch: pytest.MonkeyPatch):
    async def _run(doc: dict[str, Any], grn_result=None, miro_result=None):
        h = Harness(doc, grn_result, miro_result)

        class Repo:
            def __init__(self, session: Any) -> None: ...
            async def find_by_document_id(self, _: str) -> dict[str, Any]:
                return h.doc
            async def update_status(self, *a: Any, **k: Any) -> None: ...

        class Session:
            async def commit(self) -> None: ...
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False

        @asynccontextmanager
        async def session_factory():
            yield Session()

        import src.database
        import src.repositories.document_repository as dr
        import src.workers.migo_worker as mw
        import src.workers.sap_worker as sw

        monkeypatch.setattr(src.database, "AsyncSessionLocal", session_factory)
        monkeypatch.setattr(dr, "DocumentRepository", Repo)
        monkeypatch.setattr(mw, "run_migo_direct", h.migo)
        monkeypatch.setattr(sw, "run_miro_direct", h.miro)
        monkeypatch.setattr(sw, "run_validation_direct", h.validate)

        try:
            return await run_process_direct("DOC-TEST", "tester"), h
        except ProcessBlocked as exc:
            return exc, h

    return _run


# ── The happy paths ──────────────────────────────────────────────────────────

async def test_migo_then_miro_posts_both_in_order(run):
    result, h = await run(make_doc("migo_then_miro"), OK_GRN, OK_MIRO)

    assert h.calls == ["MIGO", "MIRO"]
    assert result["posted"] is True
    assert result["grn_number"] == "4900004378"
    assert result["miro_number"] == "5105609733"


async def test_miro_direct_skips_the_goods_receipt(run):
    result, h = await run(make_doc("miro_direct"), None, OK_MIRO)

    assert "MIGO" not in h.calls
    assert result["posted"] is True


# ── What must not happen twice ───────────────────────────────────────────────

async def test_retry_after_partial_failure_does_not_repost_the_gr(run):
    """The critical one.

    A previous attempt posted the GR and then failed at the invoice. Retrying
    must resume at the invoice; re-posting would duplicate stock movement that
    cannot be undone from this application.
    """
    result, h = await run(make_doc("migo_then_miro", grn=OK_GRN), None, OK_MIRO)

    assert h.calls == ["MIRO"]
    assert "MIGO" not in h.calls
    assert result["posted"] is True
    assert any("skipped" in s for s in result["steps"])


async def test_already_posted_document_is_refused(run):
    result, h = await run(make_doc("miro_direct", miro=OK_MIRO), None, OK_MIRO)

    assert isinstance(result, ProcessBlocked)
    assert result.detail == "ALREADY_POSTED"
    assert h.calls == []


# ── Failure must not cascade ─────────────────────────────────────────────────

async def test_failed_gr_stops_before_the_invoice(run):
    """An invoice posted against a receipt that does not exist is worse than
    an invoice not posted at all."""
    result, h = await run(make_doc("migo_then_miro"), BAD_GRN, OK_MIRO)

    assert isinstance(result, ProcessBlocked)
    assert result.detail == "GR_FAILED"
    assert h.calls == ["MIGO"]


async def test_failed_invoice_keeps_the_goods_receipt(run):
    result, h = await run(make_doc("migo_then_miro"), OK_GRN, BAD_MIRO)

    assert h.calls == ["MIGO", "MIRO"]
    assert result["posted"] is False
    assert result["grn_number"] == "4900004378"


async def test_failed_validation_posts_nothing(run):
    result, h = await run(
        make_doc("miro_direct", validation={"is_valid": False, "recommendation": "GSTIN mismatch"}),
        None, OK_MIRO,
    )

    assert isinstance(result, ProcessBlocked)
    assert result.detail == "VALIDATION_FAILED"
    assert h.calls == []


# ── Non-executable routes ────────────────────────────────────────────────────

@pytest.mark.parametrize(
    ("route", "detail"),
    [("hold", "ROUTE_HOLD"), ("fb60", "FB60_FORM_REQUIRED"), ("", "NOT_ROUTED")],
)
async def test_non_executable_routes_are_refused_without_posting(run, route: str, detail: str):
    result, h = await run(make_doc(route), OK_GRN, OK_MIRO)

    assert isinstance(result, ProcessBlocked)
    assert result.detail == detail
    assert h.calls == []


async def test_missing_validation_is_run_before_posting(run):
    """Service PO refuses to post without its gates, and the pipeline does not
    validate on upload — so the chain must fill that in rather than dead-end."""
    doc = make_doc("miro_direct")
    doc["sap_validation"] = None
    result, h = await run(doc, None, OK_MIRO)

    assert h.calls[0] == "VALIDATE"
