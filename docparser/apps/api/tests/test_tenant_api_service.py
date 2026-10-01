"""Resolving a customer's SAP endpoint.

The failure mode that matters is silent cross-tenant posting: resolving to the
wrong customer's SAP, or quietly falling back to the shared default when a
customer *is* configured. Both send a real document to the wrong system.
"""
from typing import Any

import pytest

from src.services.tenant_api_service import ResolvedEndpoint, build_payload, resolve


class Row:
    """Stands in for a TenantApiConfigRow."""

    def __init__(self, **kw: Any) -> None:
        self.full_url = kw.get("full_url", "")
        self.base_url = kw.get("base_url", "")
        self.path = kw.get("path", "")
        self.method = kw.get("method", "POST")
        self.sap_client = kw.get("sap_client", "800")
        self.username = kw.get("username", "")
        self.password = kw.get("password", "")
        self.extra_headers = kw.get("extra_headers", {})
        self.payload_template = kw.get("payload_template", {})
        self.is_active = kw.get("is_active", True)


@pytest.fixture
def with_row(monkeypatch: pytest.MonkeyPatch):
    """Install a fake DB lookup returning `row` (or None)."""
    def _install(row: Row | None):
        from contextlib import asynccontextmanager

        class Result:
            def scalar_one_or_none(self): return row

        class Session:
            async def execute(self, *a: Any, **k: Any): return Result()
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False

        @asynccontextmanager
        async def factory():
            yield Session()

        import src.database
        monkeypatch.setattr(src.database, "AsyncSessionLocal", factory)
    return _install


# ── Resolution ───────────────────────────────────────────────────────────────

async def test_full_url_is_used_verbatim(with_row):
    """The customer's endpoint may be any host, port, path or query string —
    there is no shared base URL and no assumption of client 800."""
    with_row(Row(full_url="https://sap.customer-b.example/api/v2/invoice?sap-client=310"))

    ep = await resolve("miro_post", tenant_id="t1", default_path="ZMIRO/MIRO")

    assert ep.url == "https://sap.customer-b.example/api/v2/invoice?sap-client=310"
    assert ep.is_fallback is False


async def test_legacy_rows_still_compose_from_base_and_path(with_row):
    """Rows saved before full_url existed must keep working."""
    with_row(Row(base_url="http://10.0.0.5:8081", path="ZMIRO/MIRO", sap_client="900"))

    ep = await resolve("miro_post", tenant_id="t1", default_path="ZMIRO/MIRO")

    assert ep.url == "http://10.0.0.5:8081/ZMIRO/MIRO?sap-client=900"


async def test_no_tenant_falls_back_to_global_settings(with_row):
    ep = await resolve("miro_post", tenant_id=None, default_path="ZMIRO/MIRO")

    assert ep.is_fallback is True
    assert ep.url.endswith("/ZMIRO/MIRO?sap-client=800")


async def test_unconfigured_tenant_falls_back(with_row):
    """A company created but never configured must not post nowhere."""
    with_row(Row(full_url="", base_url="", path=""))

    ep = await resolve("miro_post", tenant_id="t1", default_path="ZMIRO/MIRO")
    assert ep.is_fallback is True


async def test_deactivated_endpoint_falls_back(with_row):
    with_row(Row(full_url="https://sap.customer-b.example/x", is_active=False))

    ep = await resolve("miro_post", tenant_id="t1", default_path="ZMIRO/MIRO")
    assert ep.is_fallback is True


async def test_lookup_failure_does_not_break_posting(monkeypatch: pytest.MonkeyPatch):
    """A database problem while reading configuration must not take down a
    posting that would have succeeded on the default endpoint."""
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def broken():
        raise RuntimeError("db down")
        yield

    import src.database
    monkeypatch.setattr(src.database, "AsyncSessionLocal", broken)

    ep = await resolve("miro_post", tenant_id="t1", default_path="ZMIRO/MIRO")
    assert ep.is_fallback is True


async def test_credentials_and_headers_come_from_the_tenant(with_row):
    with_row(Row(full_url="https://sap.b.example/x", username="u", password="p",
                 extra_headers={"X-Company": "B"}))

    ep = await resolve("miro_post", tenant_id="t1", default_path="ZMIRO/MIRO")

    assert ep.auth == ("u", "p")
    assert ep.extra_headers == {"X-Company": "B"}


# ── Payload shaping ──────────────────────────────────────────────────────────

async def test_no_template_keeps_the_builtin_payload():
    ep = ResolvedEndpoint(url="https://x", api_key="miro_post")
    default = {"data": [{"po_number": "4500022773"}]}

    assert await build_payload(ep, {}, default_payload=default) is default


async def test_template_reshapes_the_document_for_that_customer():
    ep = ResolvedEndpoint(
        url="https://x", api_key="miro_post",
        payload_template={"Header": {"PO": "{{po_number}}", "Total": "{{gross_amount}}"}},
    )

    out = await build_payload(
        ep, {"po_number": "4500022773", "gross_amount": 702100.0},
        default_payload={"ignored": True},
    )

    assert out == {"Header": {"PO": "4500022773", "Total": 702100.0}}


async def test_a_template_missing_a_required_field_is_refused():
    """Better to fail loudly than post an invoice with no PO number."""
    ep = ResolvedEndpoint(
        url="https://x", api_key="miro_post",
        payload_template={"Header": {"PO": "{{typo_number}}"}},
    )

    with pytest.raises(ValueError, match="required"):
        await build_payload(ep, {"po_number": "4500022773"},
                            default_payload={}, required=("typo_number",))


async def test_optional_gaps_are_allowed_through():
    ep = ResolvedEndpoint(
        url="https://x", api_key="miro_post",
        payload_template={"PO": "{{po_number}}", "Note": "{{notes}}"},
    )

    out = await build_payload(ep, {"po_number": "45"}, default_payload={},
                              required=("po_number",))
    assert out == {"PO": "45", "Note": None}
