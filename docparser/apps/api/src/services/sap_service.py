"""SAP connector with pybreaker circuit breaker and tenacity retry.

Circuit breaker state is persisted in Redis so every Celery worker process
shares the same open/closed/half-open state.  The Redis storage class uses a
*synchronous* redis.Redis connection — pybreaker's storage callbacks are
inherently sync, and the sub-millisecond key lookups are acceptable overhead.

Endpoints (configured via settings):
  fetch_po_details → POST {SAP_BASE_URL}/zpo_grn/Detail?sap-client={SAP_CLIENT}
  post_miro        → POST {SAP_BASE_URL}/ZMIRO/MIRO?sap-client={SAP_CLIENT}
"""
from __future__ import annotations

import time
from typing import Any

import aiohttp
import pybreaker
import redis as sync_redis
import structlog
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.config import settings
from src.exceptions import SAPCircuitOpenError, SAPConnectionError
from src.schemas.sap import FB60Payload, FB60Response, GRNPayload, GRNResponse, MIROPayload, MIROResponse, SAPPOResponse

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Redis-backed circuit breaker storage
# ---------------------------------------------------------------------------


class _RedisCBStorage(pybreaker.CircuitBreakerStorage):
    """Shares circuit state across all Celery worker processes via Redis."""

    _TTL = 300  # key expiry so stale open-state doesn't block forever

    def __init__(self, redis_url: str, prefix: str = "sap") -> None:
        super().__init__(pybreaker.STATE_CLOSED)
        self._r = sync_redis.from_url(
            redis_url,
            decode_responses=True,
            socket_timeout=1,
            socket_connect_timeout=1,
        )
        self._state_key = f"circuit:{prefix}:state"
        self._errors_key = f"circuit:{prefix}:errors"
        self._opened_key = f"circuit:{prefix}:opened_at"

    # pybreaker reads/writes these properties during its internal state machine

    @property  # type: ignore[override]
    def state(self) -> str:
        try:
            return self._r.get(self._state_key) or pybreaker.STATE_CLOSED
        except Exception:
            return pybreaker.STATE_CLOSED

    @state.setter
    def state(self, value: str) -> None:
        try:
            self._r.set(self._state_key, value, ex=self._TTL)
            if value == pybreaker.STATE_OPEN:
                self._r.set(self._opened_key, str(time.time()), ex=self._TTL)
        except Exception:
            pass

    @property  # type: ignore[override]
    def error_count(self) -> int:
        try:
            val = self._r.get(self._errors_key)
            return int(val) if val else 0
        except Exception:
            return 0

    @error_count.setter
    def error_count(self, value: int) -> None:
        try:
            self._r.set(self._errors_key, str(value), ex=self._TTL)
        except Exception:
            pass

    def reset(self) -> None:
        try:
            self._r.delete(self._state_key, self._errors_key)
        except Exception:
            pass

    def opened_at_timestamp(self) -> float:
        """Return unix timestamp when the circuit opened (0.0 if unknown)."""
        try:
            val = self._r.get(self._opened_key)
            return float(val) if val else 0.0
        except Exception:
            return 0.0


# ---------------------------------------------------------------------------
# SAP service
# ---------------------------------------------------------------------------


class SAPService:
    def __init__(self) -> None:
        self._base_url = settings.SAP_BASE_URL.rstrip("/")
        self._client = settings.SAP_CLIENT
        # aiohttp timeout used only for GET requests (PO fetch)
        self._timeout = aiohttp.ClientTimeout(total=settings.SAP_TIMEOUT_SECONDS)
        self._auth = (
            aiohttp.BasicAuth(
                settings.SAP_USERNAME,
                settings.SAP_PASSWORD.get_secret_value(),
            )
            if settings.SAP_USERNAME
            else None
        )
        try:
            self._storage: pybreaker.CircuitBreakerStorage = _RedisCBStorage(str(settings.REDIS_URL))
        except Exception:
            self._storage = pybreaker.CircuitBreakerStorage(pybreaker.STATE_CLOSED)
        self._breaker = pybreaker.CircuitBreaker(
            fail_max=5,
            reset_timeout=60,
            state_storage=self._storage,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _sap_url(self, path: str) -> str:
        return f"{self._base_url}/{path.lstrip('/')}?sap-client={self._client}"

    def _retry_eta(self) -> int:
        elapsed = time.time() - self._storage.opened_at_timestamp()
        return max(0, int(60 - elapsed))

    async def _http_get_with_body(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        """GET request with JSON body — required by zpo_grn/Detail API."""
        import json as _json
        t0 = time.perf_counter()
        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                async with session.get(
                    url,
                    data=_json.dumps(payload),
                    headers={"Content-Type": "application/json"},
                ) as resp:
                    duration_ms = int((time.perf_counter() - t0) * 1000)
                    log.info("SAP GET request", url=url, status_code=resp.status, duration_ms=duration_ms)
                    resp.raise_for_status()
                    return await resp.json(content_type=None)
        except aiohttp.ClientResponseError as exc:
            log.warning("SAP HTTP error", url=url, status=exc.status, message=exc.message)
            raise SAPConnectionError(
                f"SAP returned HTTP {exc.status}: {exc.message}", status_code=502
            ) from exc

    async def _http_get(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        """Single raw HTTP GET — no retry or circuit logic here."""
        t0 = time.perf_counter()
        try:
            async with aiohttp.ClientSession(
                timeout=self._timeout, auth=self._auth
            ) as session:
                async with session.get(url, params=params) as resp:
                    duration_ms = int((time.perf_counter() - t0) * 1000)
                    log.info(
                        "SAP GET request",
                        url=url,
                        status_code=resp.status,
                        duration_ms=duration_ms,
                    )
                    resp.raise_for_status()
                    return await resp.json(content_type=None)
        except aiohttp.ClientResponseError as exc:
            log.warning("SAP HTTP error", url=url, status=exc.status, message=exc.message)
            raise SAPConnectionError(
                f"SAP returned HTTP {exc.status}: {exc.message}",
                status_code=502,
            ) from exc

    @staticmethod
    def _clean_numbers(obj: Any) -> Any:
        """Recursively convert whole-number floats to ints — SAP rejects 271400.0, expects 271400."""
        if isinstance(obj, dict):
            return {k: SAPService._clean_numbers(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [SAPService._clean_numbers(v) for v in obj]
        if isinstance(obj, float) and obj == int(obj):
            return int(obj)
        return obj

    async def _http_post(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Single raw HTTP POST using httpx — handles long-running SAP calls correctly."""
        import json as _json
        import httpx
        t0 = time.perf_counter()
        payload = SAPService._clean_numbers(payload)
        log.info("SAP POST payload", payload=_json.dumps(payload, indent=2))
        timeout_secs = settings.SAP_TIMEOUT_SECONDS
        auth = (
            (settings.SAP_USERNAME, settings.SAP_PASSWORD.get_secret_value())
            if settings.SAP_USERNAME
            else None
        )
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=30.0, read=float(timeout_secs), write=30.0, pool=30.0),
            auth=auth,
        ) as client:
            try:
                resp = await client.post(
                    url,
                    json=payload,
                    headers={"Content-Type": "application/json", "Accept": "application/json"},
                )
                duration_ms = int((time.perf_counter() - t0) * 1000)
                raw_text = resp.text
                log.info(
                    "SAP POST request",
                    url=url,
                    status_code=resp.status_code,
                    duration_ms=duration_ms,
                    response_body=raw_text,
                )
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as exc:
                log.warning("SAP HTTP error", url=url, status=exc.response.status_code)
                raise SAPConnectionError(
                    f"SAP returned HTTP {exc.response.status_code}",
                    status_code=502,
                ) from exc
            except httpx.TimeoutException as exc:
                log.error("SAP POST timed out", url=url, timeout=timeout_secs)
                raise SAPConnectionError(
                    f"SAP MIRO timed out after {timeout_secs}s",
                    status_code=504,
                ) from exc

    async def _fetch_po_raw(self, po_number: str) -> dict[str, Any]:
        """Retry-wrapped PO fetch — GET with PO number in JSON body."""
        url = self._sap_url("zpo_grn/Detail")
        import json as _json
        async for attempt in AsyncRetrying(
            wait=wait_exponential(multiplier=1, min=2, max=10),
            stop=stop_after_attempt(3),
            retry=retry_if_exception_type(aiohttp.ClientError),
            reraise=True,
        ):
            with attempt:
                return await self._http_get_with_body(url, {"PO": po_number})
        raise SAPConnectionError("PO fetch failed after all retries")  # unreachable

    async def _post_miro_raw(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Single MIRO POST — no retry to prevent duplicate invoice creation in SAP."""
        url = self._sap_url("ZMIRO/MIRO")
        return await self._http_post(url, payload)

    async def _post_grn_raw(self, payload: dict[str, Any]) -> Any:
        """Single GRN POST — no retry to prevent duplicate GR creation in SAP.

        SAP returns HTTP 500 with a JSON list of messages when MIGO is already done.
        We parse and return that body instead of raising, so the caller can detect it.
        """
        import httpx
        url = self._sap_url("ZMIGO/GRN")
        cleaned = SAPService._clean_numbers(payload)
        timeout_secs = settings.SAP_TIMEOUT_SECONDS
        auth = (
            (settings.SAP_USERNAME, settings.SAP_PASSWORD.get_secret_value())
            if settings.SAP_USERNAME
            else None
        )
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=30.0, read=float(timeout_secs), write=30.0, pool=30.0),
            auth=auth,
        ) as client:
            resp = await client.post(
                url,
                json=cleaned,
                headers={"Content-Type": "application/json", "Accept": "application/json"},
            )
            log.info(
                "SAP POST request",
                url=url,
                status_code=resp.status_code,
                duration_ms=0,
                response_body=resp.text,
            )
            # SAP sends 500 + a message list when MIGO is already done — return the body as-is
            if resp.status_code == 500:
                try:
                    return resp.json()
                except Exception:
                    raise SAPConnectionError(f"SAP returned HTTP 500", status_code=502)
            resp.raise_for_status()
            return resp.json()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def fetch_po_details(self, po_number: str) -> SAPPOResponse:
        """Fetch PO + GRN details from SAP."""
        log.info("fetching PO from SAP", po_number=po_number)
        raw: dict[str, Any] = await self._fetch_po_raw(po_number)

        from src.schemas.sap import SAPGRNDetail, SAPPOLineItem

        line_items = []
        for item in raw.get("PO_LINE_ITEMS", []):
            grn_list = [SAPGRNDetail(**g) for g in item.get("GRN", [])]
            line_items.append(SAPPOLineItem(
                ITEM_NUMBER=item.get("ITEM_NUMBER", ""),
                MATERIAL_CODE=item.get("MATERIAL_CODE", ""),
                DESCRIPTION=item.get("DESCRIPTION", ""),
                ORDERED_QUANTITY=str(item.get("ORDERED_QUANTITY", "0")).strip(),
                RECEIVED_QUANTITY=str(item.get("RECEIVED_QUANTITY", "0")).strip(),
                INVOICED_QUANTITY=str(item.get("INVOICED_QUANTITY", "0")).strip(),
                UOM=item.get("UOM", ""),
                UNIT_PRICE=str(item.get("UNIT_PRICE", "0")).strip(),
                NET_AMOUNT=str(item.get("NET_AMOUNT", "0")).strip(),
                GROSS_AMOUNT=str(item.get("GROSS_AMOUNT", "0")).strip(),
                TAX_CODE=item.get("TAX_CODE", ""),
                TAX1_RATE=item.get("TAX1_RATE", ""),
                TAX1_AMOUNT=str(item.get("TAX1_AMOUNT", "")).strip(),
                TAX2_RATE=item.get("TAX2_RATE", ""),
                TAX2_AMOUNT=str(item.get("TAX2_AMOUNT", "")).strip(),
                STATUS=item.get("STATUS", ""),
                GRN=grn_list,
            ))

        return SAPPOResponse(
            PO_NUMBER=raw.get("PO_NUMBER", ""),
            PO_DATE=raw.get("PO_DATE", ""),
            COM_CODE=raw.get("COM_CODE", ""),
            BUYER_ID=raw.get("BUYER_ID", ""),
            VENDOR_ID=raw.get("VENDOR_ID", ""),
            VENDOR_NAME=raw.get("VENDOR_NAME", ""),
            VENDOR_GSTIN=raw.get("VENDOR_GSTIN", ""),
            VENDOR_STREET=raw.get("VENDOR_STREET", ""),
            VENDOR_CITY=raw.get("VENDOR_CITY", ""),
            VENDOR_STATE=raw.get("VENDOR_STATE", ""),
            SHIP_TO_NAME=raw.get("SHIP_TO_NAME", ""),
            SHIP_TO_STREET=raw.get("SHIP_TO_STREET", ""),
            SHIP_TO_CITY=raw.get("SHIP_TO_CITY", ""),
            SHIP_TO_STATE=raw.get("SHIP_TO_STATE", ""),
            SHIP_TO_GSTIN=raw.get("SHIP_TO_GSTIN", ""),
            CURRENCY=raw.get("CURRENCY", "INR"),
            GROSS_AMOUNT=str(raw.get("GROSS_AMOUNT", "0")).strip(),
            NET_AMOUNT=str(raw.get("NET_AMOUNT", "0")).strip(),
            PO_LINE_ITEMS=line_items,
            raw_response=raw,
        )

    async def post_grn(self, payload: GRNPayload) -> GRNResponse:
        """Post the GRN payload to SAP MIGO."""
        from src.services.grn_service import parse_grn_response
        log.info("posting GRN to SAP")
        raw_payload = payload.model_dump()
        raw_result = await self._post_grn_raw(raw_payload)
        # SAP may return a list of message dicts when quantities are exceeded (MIGO already done)
        if isinstance(raw_result, list):
            raw: dict[str, Any] = {"MESSAGE_LIST": raw_result, "raw_list": raw_result}
        else:
            raw = raw_result
        return parse_grn_response(raw)

    async def post_miro(self, payload: MIROPayload) -> MIROResponse:
        """Post the MIRO invoice payload to SAP."""
        log.info("posting MIRO to SAP")
        raw_payload = payload.model_dump()
        raw: dict[str, Any] = await self._post_miro_raw(raw_payload)

        miro_number = str(raw.get("INVOICE_DOCUMENT_NO") or raw.get("MIRO_NUMBER") or "").strip()
        message = MIROResponse.parse_message(raw.get("MESSAGE", ""))

        # Detect "already done" responses from SAP
        already_done = any(
            phrase in message.lower()
            for phrase in ("already done", "already posted", "already exists", "already created")
        )

        # Extract MIRO number from message if SAP didn't return it in a dedicated field
        # e.g. "Miro has already done for this PO 5105609653"
        if not miro_number and message:
            import re as _re
            match = _re.search(r'\b(\d{10})\b', message)
            if match:
                miro_number = match.group(1)

        success = bool(miro_number) or already_done
        status = raw.get("STATUS", "S") if success else raw.get("STATUS", "") or ""

        log.info(
            "MIRO response received",
            miro_number=miro_number,
            status=status,
            success=success,
            already_done=already_done,
            message=message,
        )

        return MIROResponse(
            miro_number=miro_number,
            status=status,
            message=message,
            sap_response=raw,
            success=success,
        )


    async def post_fb60(self, payload: FB60Payload) -> FB60Response:
        """Post a Non-PO invoice to SAP FB60."""
        import re as _re
        log.info("posting FB60 to SAP")
        url = self._sap_url("zfb60/fb60post")
        raw_payload = SAPService._clean_numbers(payload.model_dump())
        raw: dict[str, Any] = await self._http_post(url, raw_payload)

        fb60_number = str(
            raw.get("DOCREFID") or raw.get("DOC_NO") or raw.get("DOCUMENT_NO") or raw.get("FB60_NUMBER") or ""
        ).strip()
        message = FB60Response.parse_message(raw.get("MESSAGE", ""))

        if not fb60_number and message:
            match = _re.search(r'\b(\d{10})\b', message)
            if match:
                fb60_number = match.group(1)

        success = bool(fb60_number)
        log.info("FB60 response received", fb60_number=fb60_number, success=success, message=message)

        return FB60Response(
            fb60_number=fb60_number,
            status=raw.get("STATUS", "S") if success else raw.get("STATUS", "") or "",
            message=message,
            sap_response=raw,
            success=success,
        )


# Module-level singleton — lazy init so imports don't connect to Redis
_sap_service: SAPService | None = None


def get_sap_service() -> SAPService:
    global _sap_service
    if _sap_service is None:
        _sap_service = SAPService()
    return _sap_service
