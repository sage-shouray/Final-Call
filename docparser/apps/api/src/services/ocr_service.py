"""Gemini Vision OCR service — extracts structured invoice data from images/PDFs.

Flow
----
1. PDF/image bytes → base64-encode (Gemini 2.0 Flash accepts PDF natively)
2. Base64-encode the file bytes
4. POST to Gemini 2.0 Flash REST API with a detailed extraction prompt
5. Strip markdown fences from response, parse JSON
6. Calculate confidence score (0.0–1.0) based on key fields present
7. Retry up to 3× with exponential back-off on transient API failures
8. Raw Gemini response stored for debugging (persisted by the caller)
"""
import asyncio
import base64
import io
import json
import re
from decimal import Decimal, InvalidOperation
from functools import partial
from typing import Any

import aiohttp
import structlog
from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from src.config import settings
from src.exceptions import OCRError

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Gemini API
# ---------------------------------------------------------------------------

_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

# Key fields used for confidence calculation
_CONFIDENCE_FIELDS = (
    "invoice_no",
    "invoice_date",
    "vendor_name",
    "vendor_gstin",
    "gross_amount",
    "taxable_amount",
    "cgst_amount",
    "sgst_amount",
)

# ---------------------------------------------------------------------------
# Extraction prompt
# ---------------------------------------------------------------------------

_EXTRACTION_PROMPT = """
You are a highly accurate document parser specialised in Indian GST tax invoices, vendor invoices, purchase orders, and commercial documents.
Carefully analyse every part of the document and extract ALL visible fields listed below.

Return ONLY valid JSON — no markdown, no explanations, no code fences.
Return null for any field that is not present or cannot be determined with confidence. Never guess.

Required JSON structure:
{
  "invoice_no": "string or null",
  "invoice_date": "DD-MM-YYYY or null",
  "due_date": "DD-MM-YYYY or null",
  "po_number": "string or null",
  "delivery_note": "string or null",
  "dispatch_doc_no": "string or null",
  "dispatched_through": "string or null",
  "destination": "string or null",

  "vendor_id": "string or null",
  "vendor_name": "string or null",
  "vendor_gstin": "string or null",
  "vendor_pan": "string or null",
  "vendor_address": "string or null",
  "vendor_state": "string or null",
  "vendor_state_code": "string or null",
  "vendor_email": "string or null",
  "vendor_phone": "string or null",

  "bill_to_name": "string or null",
  "bill_to_gstin": "string or null",
  "bill_to_address": "string or null",
  "bill_to_state": "string or null",
  "bill_to_state_code": "string or null",

  "ship_to_name": "string or null",
  "ship_to_gstin": "string or null",
  "ship_to_address": "string or null",
  "ship_to_state": "string or null",
  "ship_to_state_code": "string or null",

  "place_of_supply": "string or null",
  "reverse_charge_applicable": "Yes or No or null",
  "invoice_type": "Tax Invoice or Bill of Supply or Credit Note or Debit Note or null",

  "irn_number": "string or null",
  "eway_bill_no": "string or null",
  "eway_bill_date": "DD-MM-YYYY or null",
  "eway_bill_valid_upto": "DD-MM-YYYY or null",

  "currency": "INR",
  "taxable_amount": number_or_null,
  "cgst_rate": number_or_null,
  "cgst_amount": number_or_null,
  "sgst_rate": number_or_null,
  "sgst_amount": number_or_null,
  "igst_rate": number_or_null,
  "igst_amount": number_or_null,
  "cess_amount": number_or_null,
  "tds_amount": number_or_null,
  "tcs_amount": number_or_null,
  "discount_amount": number_or_null,
  "freight_charges": number_or_null,
  "packing_charges": number_or_null,
  "insurance_charges": number_or_null,
  "other_charges": number_or_null,
  "round_off": number_or_null,
  "tax_amount": number_or_null,
  "gross_amount": number_or_null,
  "net_amount": number_or_null,

  "payment_terms": "string or null",
  "bank_name": "string or null",
  "bank_account_no": "string or null",
  "bank_ifsc": "string or null",
  "bank_branch": "string or null",
  "bank_details": "string or null",

  "vehicle_no": "string or null",
  "lr_no": "string or null",
  "lr_date": "DD-MM-YYYY or null",
  "transport_name": "string or null",
  "mode_of_transport": "string or null",
  "terms_of_delivery": "string or null",
  "declaration": "string or null",
  "notes": "string or null",

  "line_items": [
    {
      "line_number": "00010",
      "material_code": "string or null",
      "hsn_code": "string or null",
      "description": "string or null",
      "quantity": number_or_null,
      "uom": "string or null",
      "unit_rate": number_or_null,
      "discount": number_or_null,
      "taxable_amount": number_or_null,
      "cgst_rate": number_or_null,
      "cgst_amount": number_or_null,
      "sgst_rate": number_or_null,
      "sgst_amount": number_or_null,
      "igst_rate": number_or_null,
      "igst_amount": number_or_null,
      "cess_rate": number_or_null,
      "cess_amount": number_or_null,
      "tax_code": "string or null",
      "tax_amount": number_or_null,
      "amount": number_or_null
    }
  ]
}

Extraction rules:
- Dates: always normalise to DD-MM-YYYY format (e.g. 15-03-2026)
- Amounts: return as plain numbers without currency symbols, commas, or spaces (e.g. 125000.50 not "₹1,25,000.50")
- line_number: 5-digit zero-padded integers incremented by 10 (00010, 00020, 00030...)
- If no line items are present, return an empty array []
- currency: default to "INR" if not explicitly stated
- vendor_gstin / bill_to_gstin: 15-character alphanumeric GST Identification Number
- igst_amount: extract only if IGST is separately shown; otherwise null
- cgst_amount + sgst_amount: extract when intra-state GST is shown
- taxable_amount: the pre-tax subtotal before any GST
- gross_amount: the final payable amount (after all taxes and adjustments)
- net_amount: same as gross_amount when no deductions; else amount after TDS/TCS
- irn_number: Invoice Reference Number (e-invoice, 64-char hex string)
- eway_bill_no: 12-digit EWB number
- Capture bank name, account number, IFSC, and branch separately if shown
- Extract the declaration or terms & conditions text in the "declaration" field
- For vehicle/transport details fill vehicle_no, lr_no, transport_name etc.
""".strip()

# ---------------------------------------------------------------------------
# PDF → JPEG helper (runs pdf2image in executor to avoid blocking the loop)
# ---------------------------------------------------------------------------


async def _pdf_to_jpeg_bytes(pdf_bytes: bytes) -> bytes:
    """Convert the first page of a PDF to JPEG bytes (200 DPI)."""
    try:
        from pdf2image import convert_from_bytes  # imported lazily — optional dep
    except ImportError as exc:
        raise OCRError(
            "pdf2image is not installed. Install it with: pip install pdf2image",
            error_code="OCR_DEPENDENCY_MISSING",
        ) from exc

    loop = asyncio.get_event_loop()
    images = await loop.run_in_executor(
        None,
        partial(
            convert_from_bytes,
            pdf_bytes,
            dpi=200,
            first_page=1,
            last_page=1,
            fmt="jpeg",
        ),
    )
    if not images:
        raise OCRError("PDF conversion produced no pages", error_code="OCR_PDF_CONVERSION_FAILED")

    buf = io.BytesIO()
    images[0].save(buf, format="JPEG", quality=85, optimize=True)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Gemini API call (with retry)
# ---------------------------------------------------------------------------


def _strip_json_fences(text: str) -> str:
    """Remove markdown ```json ... ``` fences if present."""
    text = text.strip()
    fence = re.match(r"^```(?:json)?\s*([\s\S]*?)\s*```$", text, re.DOTALL)
    if fence:
        return fence.group(1).strip()
    return text


async def _call_gemini_api(image_bytes: bytes, mime_type: str = "image/jpeg") -> dict[str, Any]:
    """Make a single Gemini REST call; raise OCRError on any failure."""
    api_key = settings.GEMINI_API_KEY.get_secret_value()
    if not api_key:
        raise OCRError("GEMINI_API_KEY is not configured", error_code="OCR_MISCONFIGURED")

    encoded = base64.b64encode(image_bytes).decode("ascii")
    model = settings.GEMINI_MODEL  # e.g. "gemini-1.5-pro-vision"
    url = f"{_GEMINI_BASE}/{model}:generateContent"

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": _EXTRACTION_PROMPT},
                    {"inline_data": {"mime_type": mime_type, "data": encoded}},
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.1,
            "topP": 0.95,
            "topK": 40,
            "maxOutputTokens": 8192,
            "response_mime_type": "application/json",
        },
    }

    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(url, json=payload, params={"key": api_key}) as resp:
            body = await resp.json(content_type=None)
            if resp.status != 200:
                error_msg = body.get("error", {}).get("message", str(body))
                raise OCRError(
                    f"Gemini API returned HTTP {resp.status}: {error_msg}",
                    error_code="OCR_API_ERROR",
                )

    candidates = body.get("candidates", [])
    if not candidates:
        raise OCRError("Gemini returned no candidates", error_code="OCR_EMPTY_RESPONSE")

    raw_text: str = (
        candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
    )
    if not raw_text:
        raise OCRError("Gemini response text is empty", error_code="OCR_EMPTY_RESPONSE")

    try:
        return json.loads(_strip_json_fences(raw_text))
    except json.JSONDecodeError as exc:
        raise OCRError(
            f"Gemini response is not valid JSON: {exc}",
            error_code="OCR_PARSE_ERROR",
        ) from exc


# ---------------------------------------------------------------------------
# Confidence scoring
# ---------------------------------------------------------------------------


def _calculate_confidence(data: dict[str, Any]) -> float:
    """Return a 0.0–1.0 score based on how many key fields were extracted."""
    filled = sum(1 for f in _CONFIDENCE_FIELDS if data.get(f) is not None)
    base = filled / len(_CONFIDENCE_FIELDS)

    # Bonus: any line items successfully extracted
    if data.get("line_items"):
        base = min(1.0, base + 0.05)

    return round(base, 4)


# ---------------------------------------------------------------------------
# Result normalisation
# ---------------------------------------------------------------------------


def _safe_decimal(value: Any) -> str:  # noqa: ANN401
    """Coerce a Gemini-returned value to a decimal string (stored in Mongo)."""
    if value is None:
        return "0"
    try:
        return str(Decimal(str(value)))
    except InvalidOperation:
        return "0"


def _normalise_line_items(raw_items: list[Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for idx, item in enumerate(raw_items or []):
        if not isinstance(item, dict):
            continue
        line_num = item.get("line_number")
        if not line_num:
            line_num = f"{(idx + 1) * 10:05d}"
        items.append({
            "line_number":    str(line_num),
            "material_code":  item.get("material_code") or "",
            "hsn_code":       item.get("hsn_code") or "",
            "description":    item.get("description") or "",
            "quantity":       _safe_decimal(item.get("quantity")),
            "uom":            item.get("uom") or "",
            "unit_rate":      _safe_decimal(item.get("unit_rate")),
            "discount":       _safe_decimal(item.get("discount")),
            "taxable_amount": _safe_decimal(item.get("taxable_amount")),
            "cgst_rate":      _safe_decimal(item.get("cgst_rate")),
            "cgst_amount":    _safe_decimal(item.get("cgst_amount")),
            "sgst_rate":      _safe_decimal(item.get("sgst_rate")),
            "sgst_amount":    _safe_decimal(item.get("sgst_amount")),
            "igst_rate":      _safe_decimal(item.get("igst_rate")),
            "igst_amount":    _safe_decimal(item.get("igst_amount")),
            "cess_rate":      _safe_decimal(item.get("cess_rate")),
            "cess_amount":    _safe_decimal(item.get("cess_amount")),
            "tax_code":       item.get("tax_code") or "",
            "tax_amount":     _safe_decimal(item.get("tax_amount")),
            "amount":         _safe_decimal(item.get("amount")),
            "grn_reference":  "",
        })
    return items


def _normalise_extracted(raw: dict[str, Any], raw_response: dict[str, Any]) -> dict[str, Any]:
    """Map Gemini JSON output onto the ExtractedData schema fields."""
    return {
        # ── Invoice header ────────────────────────────────────────────────
        "invoice_no":             raw.get("invoice_no") or "",
        "invoice_date":           raw.get("invoice_date") or "",
        "due_date":               raw.get("due_date") or "",
        "po_number":              raw.get("po_number") or "",
        "delivery_note":          raw.get("delivery_note") or "",
        "dispatch_doc_no":        raw.get("dispatch_doc_no") or "",
        "dispatched_through":     raw.get("dispatched_through") or "",
        "destination":            raw.get("destination") or "",
        "invoice_type":           raw.get("invoice_type") or "",
        "reverse_charge_applicable": raw.get("reverse_charge_applicable") or "",
        "place_of_supply":        raw.get("place_of_supply") or "",

        # ── e-Invoice / e-Way Bill ────────────────────────────────────────
        "irn_number":             raw.get("irn_number") or "",
        "eway_bill_no":           raw.get("eway_bill_no") or "",
        "eway_bill_date":         raw.get("eway_bill_date") or "",
        "eway_bill_valid_upto":   raw.get("eway_bill_valid_upto") or "",

        # ── Vendor ────────────────────────────────────────────────────────
        "vendor_id":              raw.get("vendor_id") or "",
        "vendor_name":            raw.get("vendor_name") or "",
        "vendor_gstin":           raw.get("vendor_gstin") or "",
        "vendor_pan":             raw.get("vendor_pan") or "",
        "vendor_address":         raw.get("vendor_address") or "",
        "vendor_state":           raw.get("vendor_state") or "",
        "vendor_state_code":      raw.get("vendor_state_code") or "",
        "vendor_email":           raw.get("vendor_email") or "",
        "vendor_phone":           raw.get("vendor_phone") or "",

        # ── Buyer / Bill-to ───────────────────────────────────────────────
        "bill_to_name":           raw.get("bill_to_name") or "",
        "bill_to_gstin":          raw.get("bill_to_gstin") or "",
        "bill_to_address":        raw.get("bill_to_address") or "",
        "bill_to_state":          raw.get("bill_to_state") or "",
        "bill_to_state_code":     raw.get("bill_to_state_code") or "",

        # ── Ship-to ───────────────────────────────────────────────────────
        "ship_to_name":           raw.get("ship_to_name") or "",
        "ship_to_gstin":          raw.get("ship_to_gstin") or "",
        "ship_to_address":        raw.get("ship_to_address") or "",
        "ship_to_state":          raw.get("ship_to_state") or "",
        "ship_to_state_code":     raw.get("ship_to_state_code") or "",

        # ── Financials ────────────────────────────────────────────────────
        "currency":               raw.get("currency") or "INR",
        "taxable_amount":         _safe_decimal(raw.get("taxable_amount")),
        "cgst_rate":              _safe_decimal(raw.get("cgst_rate")),
        "cgst_amount":            _safe_decimal(raw.get("cgst_amount")),
        "sgst_rate":              _safe_decimal(raw.get("sgst_rate")),
        "sgst_amount":            _safe_decimal(raw.get("sgst_amount")),
        "igst_rate":              _safe_decimal(raw.get("igst_rate")),
        "igst_amount":            _safe_decimal(raw.get("igst_amount")),
        "cess_amount":            _safe_decimal(raw.get("cess_amount")),
        "tds_amount":             _safe_decimal(raw.get("tds_amount")),
        "tcs_amount":             _safe_decimal(raw.get("tcs_amount")),
        "discount_amount":        _safe_decimal(raw.get("discount_amount")),
        "freight_charges":        _safe_decimal(raw.get("freight_charges")),
        "packing_charges":        _safe_decimal(raw.get("packing_charges")),
        "insurance_charges":      _safe_decimal(raw.get("insurance_charges")),
        "other_charges":          _safe_decimal(raw.get("other_charges")),
        "round_off":              _safe_decimal(raw.get("round_off")),
        "tax_amount":             _safe_decimal(raw.get("tax_amount")),
        "gross_amount":           _safe_decimal(raw.get("gross_amount")),
        "net_amount":             _safe_decimal(raw.get("net_amount")),

        # ── Payment & Bank ────────────────────────────────────────────────
        "payment_terms":          raw.get("payment_terms") or "",
        "bank_name":              raw.get("bank_name") or "",
        "bank_account_no":        raw.get("bank_account_no") or "",
        "bank_ifsc":              raw.get("bank_ifsc") or "",
        "bank_branch":            raw.get("bank_branch") or "",
        "bank_details":           raw.get("bank_details") or "",

        # ── Transport / Logistics ─────────────────────────────────────────
        "vehicle_no":             raw.get("vehicle_no") or "",
        "lr_no":                  raw.get("lr_no") or "",
        "lr_date":                raw.get("lr_date") or "",
        "transport_name":         raw.get("transport_name") or "",
        "mode_of_transport":      raw.get("mode_of_transport") or "",
        "terms_of_delivery":      raw.get("terms_of_delivery") or "",

        # ── Other ─────────────────────────────────────────────────────────
        "declaration":            raw.get("declaration") or "",
        "notes":                  raw.get("notes") or "",
        "reference_doc":          "",
        "confidence_score":       _calculate_confidence(raw),
        "line_items":             _normalise_line_items(raw.get("line_items", [])),
        "raw_ocr_response":       raw_response,
    }


# ---------------------------------------------------------------------------
# Public entry-point (with retry)
# ---------------------------------------------------------------------------


async def extract_vendor_invoice(
    file_bytes: bytes,
    mime_type: str,
) -> dict[str, Any]:
    """Extract structured data from a vendor invoice image or PDF.

    Returns a dict matching the ExtractedData schema.
    Retries up to 3 times with exponential back-off on transient failures.
    """
    # Gemini 2.0 Flash accepts PDF natively — skip pdf2image/poppler entirely
    image_bytes = file_bytes
    image_mime = mime_type

    raw_gemini_response: dict[str, Any] = {}

    def _is_retryable(exc: BaseException) -> bool:
        # Do NOT retry quota errors (429) — they won't recover on retry
        if isinstance(exc, OCRError) and "429" in str(exc):
            return False
        return True

    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(2),
            wait=wait_exponential(multiplier=2, min=5, max=30),
            retry=retry_if_exception(_is_retryable),
            reraise=True,
        ):
            with attempt:
                log.info(
                    "calling Gemini OCR",
                    attempt=attempt.retry_state.attempt_number,
                    mime_type=mime_type,
                    size_bytes=len(image_bytes),
                )
                raw_gemini_response = await _call_gemini_api(image_bytes, image_mime)

    except RetryError as exc:
        raise OCRError(
            "Gemini API failed after retries (model overloaded — please retry)",
            error_code="OCR_MAX_RETRIES_EXCEEDED",
        ) from exc

    extracted = _normalise_extracted(raw_gemini_response, raw_gemini_response)
    log.info(
        "OCR extraction complete",
        invoice_no=extracted["invoice_no"],
        confidence=extracted["confidence_score"],
        line_items=len(extracted["line_items"]),
    )
    return extracted
