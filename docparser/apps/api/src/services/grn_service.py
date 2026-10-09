"""GRN payload builder — transforms SAP PO data into ZMIGO/GRN payload."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog

from src.schemas.sap import GRN103ItemData, GRN103Payload, GRNItemData, GRNPayload, GRNResponse, SAPPOResponse

log = structlog.get_logger(__name__)


def _today_ddmmyyyy() -> str:
    return datetime.now(UTC).strftime("%d.%m.%Y")


def _today_yyyymmdd() -> str:
    return datetime.now(UTC).strftime("%Y%m%d")


def _safe_float(value: Any) -> float:
    try:
        return float(str(value).strip().replace(",", ""))
    except (ValueError, TypeError):
        return 0.0


def build_grn_payload(
    extracted: dict[str, Any],
    sap_po: SAPPOResponse,
) -> GRNPayload:
    """Build the GRN POST payload matching the ZMIGO/GRN API format."""
    po_number: str = extracted.get("po_number") or sap_po.PO_NUMBER or ""
    vendor: str = sap_po.VENDOR_ID.strip()
    today = _today_ddmmyyyy()

    po_items: list[GRNItemData] = []
    for sap_line in sap_po.PO_LINE_ITEMS:
        quantity = _safe_float(sap_line.ORDERED_QUANTITY)
        po_items.append(
            GRNItemData(
                po_item=sap_line.ITEM_NUMBER.strip(),
                material=sap_line.MATERIAL_CODE.strip(),
                quantity=str(int(quantity)) if quantity == int(quantity) else str(quantity),
            )
        )

    log.info("GRN payload built", po_number=po_number, vendor=vendor, line_count=len(po_items))

    return GRNPayload(
        po=po_number,
        vendor=vendor,
        reference_doc_no=po_number,
        posting_date=today,
        document_date=today,
        po_items=po_items,
    )


def build_grn_103_payload(
    extracted: dict[str, Any],
    sap_po: SAPPOResponse,
    plant: str = "",
    storage_location: str = "",
) -> GRN103Payload:
    """Build the movement-type-103 GRN payload for the quality-hold workflow.

    Goods are received into blocked stock pending inspection (Sangam's process),
    not straight into unrestricted stock, so this hits a different endpoint
    (zmigo_103/GRN_103) with a different shape than the standard GRN above —
    notably a received quantity (ENTRY_QNT, what this invoice actually covers)
    kept separate from the PO's ordered quantity (PO_PR_QNT, for reference),
    since a partial delivery receives less than the PO asked for.
    """
    from src.config import settings

    po_number: str = extracted.get("po_number") or sap_po.PO_NUMBER or ""
    vendor: str = sap_po.VENDOR_ID.strip()
    site = plant or storage_location or settings.SAP_COMPANY_CODE
    today = _today_yyyymmdd()

    inv_lines: list[dict[str, Any]] = extracted.get("line_items") or []
    inv_qty_by_line = {
        str(li.get("line_number") or "").strip().lstrip("0"): li.get("quantity")
        for li in inv_lines
    }

    items: list[GRN103ItemData] = []
    for sap_line in sap_po.PO_LINE_ITEMS:
        po_item = sap_line.ITEM_NUMBER.strip()
        ordered_qty = _safe_float(sap_line.ORDERED_QUANTITY)
        # The quantity THIS invoice is receiving — falls back to the full PO
        # ordered quantity when the invoice doesn't carry its own line match
        # (a single-line invoice covering the whole PO is the common case).
        invoiced_qty = inv_qty_by_line.get(po_item.lstrip("0"))
        entry_qty = _safe_float(invoiced_qty) if invoiced_qty is not None else ordered_qty

        def _fmt(q: float) -> str:
            return str(int(q)) if q == int(q) else str(q)

        items.append(GRN103ItemData(
            PO_NUMBER=po_number,
            PO_ITEM=po_item,
            MATERIAL=sap_line.MATERIAL_CODE.strip(),
            PLANT=site,
            STGE_LOC=site,
            VENDOR=vendor,
            ENTRY_QNT=_fmt(entry_qty),
            ENTRY_UOM=sap_line.UOM.strip() or "EA",
            PO_PR_QNT=_fmt(ordered_qty),
            ORDERPR_UN=sap_line.UOM.strip() or "EA",
        ))

    log.info("GRN-103 payload built", po_number=po_number, vendor=vendor, line_count=len(items))

    return GRN103Payload(
        PSTNG_DATE=today,
        DOC_DATE=today,
        REF_DOC_NO=po_number,
        items=items,
    )


def parse_grn_response(raw: dict[str, Any]) -> GRNResponse:
    """Parse the SAP GRN API response into a GRNResponse.

    SAP returns a list [{"MESSAGE": "PU Ordered quantity exceeded ..."}] when MIGO
    was already done for the PO. This is wrapped into {"MESSAGE_LIST": [...]} by
    post_grn() before reaching here.
    """
    import re

    # Collect all message text from both flat MESSAGE and list MESSAGE_LIST
    message_parts: list[str] = []
    flat_msg = GRNResponse.parse_message(raw.get("MESSAGE", ""))
    if flat_msg:
        message_parts.append(flat_msg)

    msg_list: list[dict[str, Any]] = raw.get("MESSAGE_LIST", [])
    for entry in msg_list:
        txt = str(entry.get("MESSAGE", "")).strip()
        if txt:
            message_parts.append(txt)

    combined_message = " | ".join(message_parts)
    combined_lower = combined_message.lower()

    # Detect MIGO already done conditions
    already_done = any(
        phrase in combined_lower
        for phrase in (
            "already done",
            "already posted",
            "already exists",
            "already created",
            "pu ordered quantity exceeded",   # SAP sends this when GRN already posted
            "ordered quantity exceeded",
        )
    )

    grn_number = str(
        raw.get("DOC_NO") or raw.get("GR_NUMBER") or raw.get("MATERIAL_DOCUMENT") or raw.get("GRN_NUMBER") or ""
    ).strip()

    if not grn_number and combined_message:
        match = re.search(r"\b(\d{10})\b", combined_message)
        if match:
            grn_number = match.group(1)

    success = bool(grn_number) or already_done
    status = raw.get("STATUS", "S") if success else raw.get("STATUS", "") or ""

    # Build a clean sap_response that includes the message list if present
    sap_response: dict[str, Any] = {k: v for k, v in raw.items() if k != "raw_list"}
    if msg_list and "MESSAGE" not in sap_response:
        sap_response["MESSAGE"] = combined_message

    return GRNResponse(
        grn_number=grn_number,
        status=status,
        message=combined_message,
        sap_response=sap_response,
        success=success,
        already_done=already_done,
    )
