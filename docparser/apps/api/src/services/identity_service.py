"""Fast identity extraction — the first stage of the ingest pipeline.

Reads only page 1's embedded text layer and pulls out the two fields that decide
where a document goes: the PO number and the invoice number. No AI, no image
rendering, no network. Measured at ~29 ms median over 40 real invoices.

This deliberately extracts nothing else. Everything else (amounts, line items,
taxes, vendor details) comes from the Gemini pass running in parallel — see
src/workers/pipeline_worker.py. Keeping this layer to two fields is what keeps
it reliable; the moment it starts guessing amounts it inherits OCR's error modes
without OCR's accuracy.

pypdf is used rather than PyMuPDF: identical hit rate on real invoices (36/36),
~25 ms slower, and BSD-licensed rather than AGPL — which matters for a hosted
commercial product.
"""
from __future__ import annotations

import asyncio
import io
import re
import time
from typing import Any

import structlog

# Imported at module level, not inside the hot path: a lazy import made the very
# first extraction in a worker process pay ~1 s of import cost, which is 35× the
# work itself.
from pypdf import PdfReader

from src.config import settings

log = structlog.get_logger(__name__)


# A page with less text than this has no usable text layer — it's a scan, and
# only the OCR pass can read it.
_MIN_TEXT_CHARS = 50

# Labels that mark a nearby number as the PO reference. Used to rank candidates
# when a page contains several numbers in the SAP PO range.
_PO_LABEL = re.compile(r"\b(p\.?\s?o\.?|purchase\s+order|order\s+no)\b", re.IGNORECASE)

_INVOICE_NO = re.compile(
    r"(?:invoice|bill|inv)[\s.]*(?:no|number|#)[\s.:\-]*([A-Za-z0-9][A-Za-z0-9/\-]{2,})",
    re.IGNORECASE,
)


def _po_pattern() -> re.Pattern[str]:
    """PO numbers are 10 digits in a configured leading range (SAP: 45xxxxxxxx)."""
    prefixes = "|".join(re.escape(p.strip()) for p in settings.SAP_PO_PREFIXES.split(",") if p.strip())
    return re.compile(rf"\b((?:{prefixes})\d{{8}})\b")


def _extract_page1_text(file_bytes: bytes) -> str:
    """Blocking — read page 1's text layer. Caller must run this off the event loop."""
    reader = PdfReader(io.BytesIO(file_bytes))
    if not reader.pages:
        return ""
    return reader.pages[0].extract_text() or ""


def _rank_po_candidates(text: str) -> list[str]:
    """Return PO candidates, most likely first.

    A page can carry several numbers in the PO range (the PO itself, a reference
    to a previous one, a bank account that happens to match). Candidates whose
    line also mentions "PO"/"Purchase Order" are ranked first; SAP settles the
    rest — routing tries each in turn and stops at the one SAP recognises.
    """
    pattern = _po_pattern()
    labelled: list[str] = []
    unlabelled: list[str] = []

    for line in text.splitlines():
        matches = pattern.findall(line)
        if not matches:
            continue
        target = labelled if _PO_LABEL.search(line) else unlabelled
        for match in matches:
            if match not in target:
                target.append(match)

    # Preserve order, drop duplicates across both buckets.
    ordered: list[str] = []
    for candidate in [*labelled, *unlabelled]:
        if candidate not in ordered:
            ordered.append(candidate)
    return ordered


def _find_invoice_number(text: str) -> str:
    match = _INVOICE_NO.search(text)
    return match.group(1).strip().rstrip(".,;:") if match else ""


async def extract_identity(file_bytes: bytes) -> dict[str, Any]:
    """Pull the PO number and invoice number from page 1's text layer.

    Never raises — a document we cannot read fast is not an error, it just falls
    back to the OCR pass. `has_text_layer=False` means the PDF is a scan and the
    fast route is unavailable for it.
    """
    started = time.perf_counter()

    try:
        # PDF parsing is CPU-bound; off-thread it so it cannot stall the event loop.
        text = await asyncio.to_thread(_extract_page1_text, file_bytes)
    except Exception as exc:
        log.warning("fast identity extraction failed — falling back to OCR", error=str(exc))
        return {
            "has_text_layer": False,
            "po_candidates": [],
            "po_number": "",
            "invoice_no": "",
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
            "error": str(exc),
        }

    has_text_layer = len(text.strip()) >= _MIN_TEXT_CHARS
    candidates = _rank_po_candidates(text) if has_text_layer else []
    invoice_no = _find_invoice_number(text) if has_text_layer else ""
    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)

    log.info(
        "fast identity extracted",
        has_text_layer=has_text_layer,
        po_candidates=candidates,
        invoice_no=invoice_no,
        elapsed_ms=elapsed_ms,
    )

    return {
        "has_text_layer": has_text_layer,
        "po_candidates": candidates,
        "po_number": candidates[0] if candidates else "",
        "invoice_no": invoice_no,
        "text_chars": len(text),
        "elapsed_ms": elapsed_ms,
    }
