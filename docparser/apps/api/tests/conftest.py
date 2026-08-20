"""Shared fixtures.

Every test here runs fully offline. Two of the endpoints these modules talk to
are destructive — ZSPO_VALD/SERV_PO_VAL posts a MIRO and MIGO posts real stock
movement — so the suite must never reach SAP. `no_sap` is autouse to make that
structural rather than a thing each test has to remember.
"""
from typing import Any

import pytest


@pytest.fixture(autouse=True)
def no_sap(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail loudly if a test makes an HTTP request.

    Guarding the HTTP clients rather than raw sockets: asyncio builds its event
    loop on a localhost socketpair, so blocking socket.connect breaks the test
    runner itself before any test code runs.
    """
    def _blocked(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError(
            "A test attempted a real HTTP request. SAP calls must be mocked — "
            "SERV_PO_VAL posts a MIRO and MIGO posts stock movement."
        )

    import httpx
    monkeypatch.setattr(httpx.Client, "send", _blocked, raising=False)
    monkeypatch.setattr(httpx.AsyncClient, "send", _blocked, raising=False)
    try:
        import aiohttp
        monkeypatch.setattr(aiohttp.ClientSession, "_request", _blocked, raising=False)
    except ImportError:
        pass


def po_response(
    *,
    po_number: str = "4500022773",
    line_type: str = "NB",
    gr_number: str = "",
    ses_number: str = "",
    ordered: str = "10",
    net_amount: str = "1000.00",
    items: int = 1,
) -> dict[str, Any]:
    """Build a zpo_grn/Detail payload shaped like the real one.

    Field placement matters and is easy to get wrong: TYPE lives only on the raw
    line, material lines confirm via GR_NUMBER, and service lines via SSES_NO
    with GR_NUMBER left empty — the mix-up that made every service PO look
    unconfirmed in production.
    """
    lines = []
    for i in range(items):
        item_no = f"{(i + 1) * 10:05d}"
        grn: list[dict[str, Any]] = []
        if gr_number or ses_number:
            grn = [{
                "GR_NUMBER": gr_number,
                "SSES_NO": ses_number,
                "GR_DATE": "20260820",
                "PO_ITEM_NUMBER": item_no,
                "GR_QUANTITY": ordered,
                "NET_AMOUNT": net_amount,
            }]
        lines.append({
            "ITEM_NUMBER": item_no,
            "TYPE": line_type,
            "MATERIAL_CODE": "" if line_type == "ZSER" else "ZSRO202500000001",
            "ORDERED_QUANTITY": ordered,
            "RECEIVED_QUANTITY": ordered,
            "NET_AMOUNT": net_amount,
            "GROSS_AMOUNT": net_amount,
            "UNIT_PRICE": net_amount,
            "GR_EXPECTED": "Open",
            "TAX_CODE": "R1",
            "UOM": "EA",
            "GRN": grn,
        })
    return {
        "PO_NUMBER": po_number,
        "COM_CODE": "SSDN",
        "BUYER_ID": "SSDN",
        "VENDOR_NAME": "Sage Technologies",
        "VENDOR_GSTIN": "09AAACC1206D2ZJ",
        "CURRENCY": "INR",
        "GROSS_AMOUNT": net_amount,
        "NET_AMOUNT": net_amount,
        "PO_LINE_ITEMS": lines,
    }
