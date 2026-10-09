"""Multi-invoice PDF splitting — the first stage ahead of ingestion.

A single uploaded or emailed PDF can legitimately contain several distinct
invoices merged into one file (a vendor batching a week's invoices into one
attachment is the common case). Built on a single-invoice assumption, the rest
of the pipeline reads whichever fields land on the page it happens to look at
and silently drops the other invoices — no error, no row, nothing to retry.

This module decides, before a document is created at all, how many invoices a
PDF actually contains and where the boundaries between them fall, so the
caller (ingestion_service) can split the bytes and run each invoice through
the existing single-invoice pipeline unchanged, as its own document.

Two-signal boundary detection, reusing the exact regexes identity_service
already trusts for routing (same ~ms-scale cost, no AI, no network):

    invoice_no   changes  -> boundary
    po_number    changes  -> boundary
    neither present       -> continuation of the current invoice (a second
                              page of line items carries no header fields)

A page with no usable text layer (a scan) cannot be read by either signal.
For a fully-scanned PDF (no page has a text layer), one Gemini call reads the
whole document and reports the invoice/PO identity it can see on each page —
expensive relative to the regex path, but paid once per document, not once
per page, and only for the case regex genuinely cannot handle. A PDF with a
*mix* of text and scanned pages is rarer and harder to reason about safely,
so it still falls back to one segment flagged `needs_review` rather than
guessing.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Any

import structlog
from pypdf import PdfReader, PdfWriter

from src.services.identity_service import _MIN_TEXT_CHARS, _find_invoice_number, _rank_po_candidates

log = structlog.get_logger(__name__)

_BOUNDARY_PROMPT_TEMPLATE = """
This PDF has {page_count} pages. It may contain more than one invoice merged
into a single file. For EVERY page, identify the invoice number and PO
(purchase order) number visible on that page. If a page is a continuation of
the previous page's invoice (e.g. more line items, no new header), repeat
that same invoice's invoice_no and po_number for it rather than leaving them
null. If a field is genuinely not visible anywhere on the page, use null.

Return ONLY valid JSON, no markdown, no explanation — an array with exactly
{page_count} entries, one per page in order:

[
  {{"page": 1, "invoice_no": "string or null", "po_number": "string or null"}},
  ...
]
""".strip()


@dataclass(slots=True)
class Segment:
    start_page: int  # 0-indexed, inclusive
    end_page: int     # 0-indexed, inclusive
    invoice_no: str
    po_number: str
    confidence: str   # "high" | "low"
    reason: str


@dataclass(slots=True)
class SegmentationResult:
    segments: list[Segment] = field(default_factory=list)
    page_count: int = 0

    @property
    def is_multi_invoice(self) -> bool:
        return len(self.segments) > 1


def _page_texts(file_bytes: bytes) -> list[str]:
    """Blocking — read every page's text layer. Caller must off-thread this."""
    reader = PdfReader(io.BytesIO(file_bytes))
    return [page.extract_text() or "" for page in reader.pages]


def _page_identity(text: str) -> tuple[str, str, bool]:
    """invoice_no, po_number, has_text_layer — reusing identity_service's regexes."""
    has_text_layer = len(text.strip()) >= _MIN_TEXT_CHARS
    if not has_text_layer:
        return "", "", False
    candidates = _rank_po_candidates(text)
    invoice_no = _find_invoice_number(text)
    return invoice_no, (candidates[0] if candidates else ""), True


def _group_pages_into_segments(identities: list[tuple[str, str]]) -> list[Segment]:
    """Turn a per-page (invoice_no, po_number) list into segments.

    Shared by both the regex path (digital text) and the Gemini path (scanned)
    so a boundary is decided the same way regardless of how the per-page
    identity was read: a new segment starts when either field changes from
    the current segment's identity; a page with neither field present is
    treated as a continuation, not a boundary.
    """
    segments: list[Segment] = []
    if not identities:
        return segments

    seg_start = 0
    seg_invoice_no, seg_po_number = identities[0]

    def _close_segment(end_page: int, invoice_no: str, po_number: str) -> None:
        both = bool(invoice_no) and bool(po_number)
        segments.append(Segment(
            start_page=seg_start, end_page=end_page,
            invoice_no=invoice_no, po_number=po_number,
            confidence="high" if both else "low",
            reason="invoice number and PO number both identified"
                   if both else "only one boundary signal identified on this segment's first page",
        ))

    for i in range(1, len(identities)):
        invoice_no, po_number = identities[i]
        if not invoice_no and not po_number:
            continue  # continuation page (line items, terms) — no boundary signal at all

        invoice_changed = bool(invoice_no) and invoice_no != seg_invoice_no
        po_changed = bool(po_number) and po_number != seg_po_number
        if invoice_changed or po_changed:
            _close_segment(i - 1, seg_invoice_no, seg_po_number)
            seg_start = i
            seg_invoice_no, seg_po_number = invoice_no, po_number
        else:
            # Same invoice continuing — adopt whichever signal this page adds
            # that the first page of the segment didn't have.
            seg_invoice_no = seg_invoice_no or invoice_no
            seg_po_number = seg_po_number or po_number

    _close_segment(len(identities) - 1, seg_invoice_no, seg_po_number)
    return segments


async def _detect_scanned_boundaries(file_bytes: bytes, page_count: int) -> list[Segment] | None:
    """One Gemini call reads a fully-scanned PDF and reports each page's identity.

    Returns None (never raises) if Gemini is unavailable, errors, or returns a
    malformed response — the caller falls back to the conservative single-
    segment/needs-review behaviour exactly as if this function didn't exist.
    """
    from src.services.ocr_service import _call_gemini_api

    prompt = _BOUNDARY_PROMPT_TEMPLATE.format(page_count=page_count)
    try:
        response = await _call_gemini_api(file_bytes, "application/pdf", prompt=prompt)
    except Exception as exc:
        log.warning("segmentation: scanned-PDF boundary check failed", error=str(exc))
        return None

    pages = response if isinstance(response, list) else response.get("pages")
    if not isinstance(pages, list) or len(pages) != page_count:
        log.warning(
            "segmentation: scanned-PDF boundary response malformed",
            expected_pages=page_count, got=type(pages).__name__,
        )
        return None

    identities: list[tuple[str, str]] = []
    for entry in pages:
        if not isinstance(entry, dict):
            return None
        identities.append((
            str(entry.get("invoice_no") or "").strip(),
            str(entry.get("po_number") or "").strip(),
        ))

    return _group_pages_into_segments(identities)


async def detect_segments(file_bytes: bytes) -> SegmentationResult:
    """Decide how many invoices `file_bytes` contains and where each starts.

    Never raises — a PDF this cannot read falls back to one segment covering
    the whole document, identical to pre-segmentation behaviour.
    """
    import asyncio

    try:
        texts = await asyncio.to_thread(_page_texts, file_bytes)
    except Exception as exc:
        log.warning("segmentation: could not read pages — treating as single invoice", error=str(exc))
        return SegmentationResult(segments=[], page_count=0)

    page_count = len(texts)
    if page_count <= 1:
        return SegmentationResult(segments=[], page_count=page_count)

    identities = [_page_identity(t) for t in texts]
    text_layer_flags = [has_layer for _, _, has_layer in identities]

    if not any(text_layer_flags):
        # Fully scanned — regex has nothing to read on any page. This is the
        # one case worth paying for a Gemini pass over the whole document.
        scanned_segments = await _detect_scanned_boundaries(file_bytes, page_count)
        if scanned_segments is not None:
            log.info(
                "segmentation detected (scanned, via Gemini)",
                page_count=page_count,
                segment_count=len(scanned_segments),
                segments=[(s.start_page, s.end_page, s.invoice_no, s.po_number, s.confidence)
                          for s in scanned_segments],
            )
            return SegmentationResult(segments=scanned_segments, page_count=page_count)

        return SegmentationResult(
            segments=[Segment(
                start_page=0, end_page=page_count - 1,
                invoice_no="", po_number="", confidence="low",
                reason="Scanned PDF with no text layer, and the Gemini boundary "
                       "check could not run or returned an unusable result — needs review.",
            )],
            page_count=page_count,
        )

    if not all(text_layer_flags):
        # A mix of text and scanned pages — rarer and harder to reason about
        # safely than either pure case, so stay conservative rather than guess.
        return SegmentationResult(
            segments=[Segment(
                start_page=0, end_page=page_count - 1,
                invoice_no="", po_number="", confidence="low",
                reason="Some pages have a text layer and some don't — "
                       "automatic boundary detection is not reliable; needs review.",
            )],
            page_count=page_count,
        )

    segments = _group_pages_into_segments([(inv, po) for inv, po, _ in identities])

    log.info(
        "segmentation detected",
        page_count=page_count,
        segment_count=len(segments),
        segments=[(s.start_page, s.end_page, s.invoice_no, s.po_number, s.confidence) for s in segments],
    )

    return SegmentationResult(segments=segments, page_count=page_count)


def split_pdf_bytes(file_bytes: bytes, start_page: int, end_page: int) -> bytes:
    """Blocking — extract pages [start_page, end_page] (inclusive) as a new PDF."""
    reader = PdfReader(io.BytesIO(file_bytes))
    writer = PdfWriter()
    for i in range(start_page, end_page + 1):
        writer.add_page(reader.pages[i])
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()
