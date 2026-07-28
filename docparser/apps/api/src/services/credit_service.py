"""Credit-note comparison — diffs an extracted credit-note invoice's line
items against the line items already posted to SAP via MIRO for the same PO,
and classifies the result as a Credit Memo or a Subsequent Credit.

Classification rule:
  - Any line where quantity differs (with or without a price change) → CREDIT_MEMO
  - Only price differs anywhere, quantity/material unchanged on every line → SUBSEQUENT_CREDIT
  - No differences found on any matched line → no credit_case (nothing to post)
"""
from __future__ import annotations

from typing import Any

import structlog

from src.models.document import CreditCase
from src.schemas.documents import CreditComparisonResponse, CreditLineDiff
from src.schemas.sap import MIRODetailResponse

log = structlog.get_logger(__name__)

_AMOUNT_TOLERANCE = 0.01  # ignore sub-paise floating point noise


def _safe_float(value: Any) -> float:
    try:
        return round(float(str(value).strip().replace(",", "")), 2)
    except (ValueError, TypeError):
        return 0.0


def _po_item_from_line_number(line_number: str) -> str:
    """Extracted line_number is a 5-digit string like '00010'; MIRO's PO_ITEM
    is the same value as an int (10). Normalise both to a comparable int-string."""
    try:
        return str(int(str(line_number).strip() or "0"))
    except ValueError:
        return ""


def compare_credit_note(
    document_id: str,
    extracted: dict[str, Any],
    miro: MIRODetailResponse,
) -> CreditComparisonResponse:
    po_number = extracted.get("po_number") or ""

    if not miro.miro_posted:
        return CreditComparisonResponse(
            document_id=document_id,
            po_number=po_number,
            miro_posted=False,
            miro_message=miro.MESSAGE or "No MIRO posted against this PO yet.",
            credit_case=None,
            reason="No prior MIRO found for this PO — nothing to compare against.",
            line_diffs=[],
        )

    # Index the originally-posted MIRO lines by PO_ITEM for matching
    miro_by_item = {str(item.PO_ITEM): item for item in miro.DATA}

    line_diffs: list[CreditLineDiff] = []
    any_quantity_changed = False
    any_price_changed = False
    any_matched = False

    for line in extracted.get("line_items", []):
        line_number = str(line.get("line_number") or "")
        po_item = _po_item_from_line_number(line_number)
        miro_line = miro_by_item.get(po_item)

        extracted_qty = _safe_float(line.get("quantity"))
        extracted_price = _safe_float(line.get("unit_rate"))
        extracted_amount = _safe_float(line.get("amount"))
        extracted_tax = _safe_float(line.get("tax_amount"))

        if miro_line is None:
            line_diffs.append(CreditLineDiff(
                line_number=line_number,
                po_item=po_item,
                material_code=line.get("material_code") or "",
                extracted_quantity=extracted_qty,
                extracted_price=extracted_price,
                extracted_amount=extracted_amount,
                extracted_tax=extracted_tax,
                matched=False,
            ))
            continue

        any_matched = True
        miro_qty = _safe_float(miro_line.QUANTITY)
        miro_price = _safe_float(miro_line.PRICE_PER_UNIT)
        qty_changed = abs(extracted_qty - miro_qty) > _AMOUNT_TOLERANCE
        price_changed = abs(extracted_price - miro_price) > _AMOUNT_TOLERANCE

        any_quantity_changed = any_quantity_changed or qty_changed
        any_price_changed = any_price_changed or price_changed

        line_diffs.append(CreditLineDiff(
            line_number=line_number,
            po_item=po_item,
            material_code=line.get("material_code") or "",
            extracted_quantity=extracted_qty,
            miro_quantity=miro_qty,
            quantity_changed=qty_changed,
            extracted_price=extracted_price,
            miro_price=miro_price,
            price_changed=price_changed,
            extracted_amount=extracted_amount,
            miro_amount=_safe_float(miro_line.NET_AMOUNT),
            extracted_tax=extracted_tax,
            miro_tax=_safe_float(miro_line.TAX_AMOUNT),
            matched=True,
        ))

    if not any_matched:
        credit_case = None
        reason = "None of the extracted line items matched a PO item already posted via MIRO."
    elif any_quantity_changed:
        credit_case = CreditCase.CREDIT_MEMO
        reason = "Quantity differs from the originally posted MIRO on at least one line."
    elif any_price_changed:
        credit_case = CreditCase.SUBSEQUENT_CREDIT
        reason = "Only the price differs from the originally posted MIRO; quantity and material are unchanged."
    else:
        credit_case = None
        reason = "No difference found between the extracted invoice and the posted MIRO."

    return CreditComparisonResponse(
        document_id=document_id,
        po_number=po_number,
        miro_posted=True,
        miro_message=miro.MESSAGE,
        credit_case=credit_case.value if credit_case else None,
        reason=reason,
        line_diffs=line_diffs,
    )
