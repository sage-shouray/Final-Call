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
    "po_number",
    "vendor_name",
    "vendor_gstin",
    "gross_amount",
)

# ---------------------------------------------------------------------------
# Extraction prompt
# ---------------------------------------------------------------------------

_EXTRACTION_PROMPT = """
You are a highly accurate document parser specialised in vendor invoices and purchase orders.
Analyse the document image and extract the following fields.

Return ONLY valid JSON — no markdown, no explanations, no code fences.
Return null for any field that is not present or cannot be determined with confidence. Never guess.

Required JSON structure:
{
  "invoice_no": "string or null",
  "invoice_date": "DD-MM-YYYY or null",
  "po_number": "string or null",
  "vendor_id": "string or null",
  "vendor_name": "string or null",
  "vendor_gstin": "string or null",
  "vendor_address": "string or null",
  "bill_to_name": "string or null",
  "bill_to_address": "string or null",
  "ship_to_name": "string or null",
  "ship_to_address": "string or null",
  "currency": "INR",
  "gross_amount": number_or_null,
  "tax_amount": number_or_null,
  "net_amount": number_or_null,
  "payment_terms": "string or null",
  "bank_details": "string or null",
  "line_items": [
    {
      "line_number": "00010",
      "material_code": "string or null",
      "description": "string or null",
      "quantity": number_or_null,
      "uom": "string or null",
      "unit_rate": number_or_null,
      "amount": number_or_null,
      "tax_code": "string or null",
      "tax_amount": number_or_null,
      "hsn_code": "string or null"
    }
  ]
}

Extraction rules:
- Dates: always normalise to DD-MM-YYYY format (e.g. 15-03-2026)
- Amounts: return as plain numbers without currency symbols, commas, or spaces
  (e.g. 125000.50 not "₹1,25,000.50")
- line_number: 5-digit zero-padded integers incremented by 10 (00010, 00020, 00030...)
- If no line items are present, return an empty array []
- currency: default to "INR" if not explicitly stated
- vendor_gstin: 15-character GST identification number
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
            "maxOutputTokens": 4096,
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
            line_num = f"{(idx + 1) * 10:05d}"  # auto-assign 00010, 00020 …
        items.append({
            "line_number": str(line_num),
            "material_code": item.get("material_code") or "",
            "description": item.get("description") or "",
            "quantity": _safe_decimal(item.get("quantity")),
            "uom": item.get("uom") or "",
            "unit_rate": _safe_decimal(item.get("unit_rate")),
            "amount": _safe_decimal(item.get("amount")),
            "tax_code": item.get("tax_code") or "",
            "tax_amount": _safe_decimal(item.get("tax_amount")),
            "hsn_code": item.get("hsn_code") or "",
            "grn_reference": "",
        })
    return items


def _normalise_extracted(raw: dict[str, Any], raw_response: dict[str, Any]) -> dict[str, Any]:
    """Map Gemini JSON output onto the ExtractedData schema fields."""
    return {
        "invoice_no": raw.get("invoice_no") or "",
        "invoice_date": raw.get("invoice_date") or "",
        "po_number": raw.get("po_number") or "",
        "vendor_id": raw.get("vendor_id") or "",
        "vendor_name": raw.get("vendor_name") or "",
        "vendor_gstin": raw.get("vendor_gstin") or "",
        "vendor_address": raw.get("vendor_address") or "",
        "bill_to_name": raw.get("bill_to_name") or "",
        "bill_to_address": raw.get("bill_to_address") or "",
        "ship_to_name": raw.get("ship_to_name") or "",
        "ship_to_address": raw.get("ship_to_address") or "",
        "currency": raw.get("currency") or "INR",
        "gross_amount": _safe_decimal(raw.get("gross_amount")),
        "tax_amount": _safe_decimal(raw.get("tax_amount")),
        "net_amount": _safe_decimal(raw.get("net_amount")),
        "payment_terms": raw.get("payment_terms") or "",
        "bank_details": raw.get("bank_details") or "",
        "reference_doc": "",
        "confidence_score": _calculate_confidence(raw),
        "line_items": _normalise_line_items(raw.get("line_items", [])),
        "raw_ocr_response": raw_response,
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

    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(5),
            wait=wait_exponential(multiplier=2, min=5, max=60),
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
            "Gemini API failed after 5 attempts (model overloaded — please retry)",
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
