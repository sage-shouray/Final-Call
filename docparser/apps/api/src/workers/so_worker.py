"""Sales Order worker — builds SO payload from extracted data and simulates/posts via SAP VA01 APIs."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog

log = structlog.get_logger(__name__)


def _today_yyyymmdd() -> str:
    return datetime.now(UTC).strftime("%Y%m%d")


def _build_so_payload(extracted: dict[str, Any], customer: dict[str, Any]) -> dict[str, Any]:
    from src.schemas.sap import SOItemData, SOPartnerData, SOPayload, SOScheduleData

    customer_id = customer.get("CUSTOMER", "")
    sales_org   = customer.get("SALES_ORGANIZATION", "")
    distr_chan  = customer.get("DISTRIBUTION_CHANNEL", "")
    division    = customer.get("DIVISION", "")

    partners = [
        SOPartnerData(partn_role="AG", partn_numb=customer_id),
        SOPartnerData(partn_role="WE", partn_numb=customer_id),
        SOPartnerData(partn_role="RE", partn_numb=customer_id),
        SOPartnerData(partn_role="RG", partn_numb=customer_id),
    ]

    items: list[SOItemData] = []
    schedules: list[SOScheduleData] = []
    line_items = extracted.get("line_items") or []

    for idx, line in enumerate(line_items):
        itm_number = f"{(idx + 1) * 10:06d}"
        material   = str(line.get("material_code") or "").strip()
        qty        = float(str(line.get("quantity") or 0).replace(",", ""))
        uom        = str(line.get("uom") or "ST").strip()
        req_date   = extracted.get("delivery_date") or _today_yyyymmdd()
        if "-" in req_date:
            parts = req_date.split("-")
            if len(parts[0]) == 2:
                req_date = f"{parts[2]}{parts[1]}{parts[0]}"
            else:
                req_date = "".join(parts)

        items.append(SOItemData(
            itm_number=itm_number,
            material=material,
            plant=str(line.get("plant") or "").strip(),
            target_qty=qty,
            target_qu=uom,
        ))
        schedules.append(SOScheduleData(
            itm_number=itm_number,
            req_date=req_date,
            req_qty=qty,
        ))

    purch_no_c = str(extracted.get("po_number") or extracted.get("invoice_no") or "").strip()
    purch_date = str(extracted.get("invoice_date") or extracted.get("po_date") or "").strip()
    if "-" in purch_date:
        parts = purch_date.split("-")
        if len(parts[0]) == 2:
            purch_date = f"{parts[2]}{parts[1]}{parts[0]}"

    payload = SOPayload(
        doc_type="TA",
        sales_org=sales_org,
        distr_chan=distr_chan,
        division=division,
        purch_no_c=purch_no_c,
        purch_date=purch_date,
        items=items,
        schedules=schedules,
        partners=partners,
    )
    return payload.model_dump()


async def _fetch_customer(session: Any, customer_id: str) -> dict[str, Any] | None:
    """Fetch customer row from the PostgreSQL customers table."""
    from sqlalchemy import text
    result = await session.execute(
        text("SELECT data FROM customers WHERE data->>'CUSTOMER' = :cid LIMIT 1"),
        {"cid": customer_id},
    )
    row = result.fetchone()
    return dict(row[0]) if row else None


async def run_so_simulate(document_id: str, customer_id: str) -> None:
    """Fetch customer, build payload, simulate via ZDATA_HOLD/DATA_SIMULATE."""
    import traceback as _tb
    from src.database import AsyncSessionLocal
    from src.models.document import DocumentStatus, SOSimulation
    from src.repositories.document_repository import DocumentRepository
    from src.services.sap_service import get_sap_service
    from src.schemas.sap import SOPayload

    bound_log = log.bind(document_id=document_id)
    bound_log.info("SO simulation started", customer_id=customer_id)

    async with AsyncSessionLocal() as session:
        doc_repo = DocumentRepository(session)
        try:
            doc = await doc_repo.find_by_document_id(document_id)
            if not doc:
                bound_log.error("document not found")
                return

            doc_id = doc["id"]
            extracted = doc.get("extracted") or {}

            customer_raw = await _fetch_customer(session, customer_id)
            if not customer_raw:
                bound_log.error("customer not in PostgreSQL cache", customer_id=customer_id)
                await doc_repo.update_status(doc_id, DocumentStatus.FAILED, error_entry={
                    "stage": "so_simulation", "message": f"Customer {customer_id} not found in cache",
                    "detail": "CUSTOMER_NOT_FOUND", "timestamp": datetime.now(UTC).isoformat(),
                })
                await session.commit()
                return

            bound_log.info("customer fetched", customer=customer_raw.get("CUSTOMER_NAME"))

            payload_dict = _build_so_payload(extracted, customer_raw)
            payload = SOPayload(**payload_dict)

            await doc_repo.update_status(doc_id, DocumentStatus.VALIDATING)
            await session.commit()

            sap = get_sap_service()
            result = await sap.simulate_sales_order(payload)

            bound_log.info("SAP simulate response", success=result.success, message=result.message)

            simulation = SOSimulation(
                payload_sent=payload_dict,
                sap_response=result.sap_response,
                status="success" if result.success else "failed",
            )
            await doc_repo.update(doc_id, {
                "so_simulation": simulation.model_dump(),
                "status":        DocumentStatus.VALIDATED.value,
            })
            await session.commit()
            bound_log.info("SO simulation saved", sim_status=simulation.status)

        except Exception as exc:
            bound_log.error("SO simulation exception", error=str(exc), traceback=_tb.format_exc())
            try:
                doc2 = await doc_repo.find_by_document_id(document_id)
                if doc2:
                    await doc_repo.update(doc2["id"], {
                        "status": DocumentStatus.VALIDATED.value,
                        "so_simulation": {
                            "status": "failed",
                            "sap_response": {"STATUS": "ERROR", "MESSAGE": str(exc)},
                            "payload_sent": {},
                            "simulated_at": datetime.now(UTC).isoformat(),
                        },
                    })
                    await session.commit()
            except Exception as db_exc:
                bound_log.error("Failed to update DB after exception", error=str(db_exc))


async def run_so_create(document_id: str, customer_id: str) -> None:
    """Build payload and create Sales Order via ZCREATE_SALESOR/SALESORDER_CREATE."""
    import traceback as _tb
    from src.database import AsyncSessionLocal
    from src.models.document import DocumentStatus
    from src.repositories.document_repository import DocumentRepository
    from src.schemas.sap import SOPayload
    from src.services.sap_service import get_sap_service

    bound_log = log.bind(document_id=document_id)
    bound_log.info("SO create started", customer_id=customer_id)

    async with AsyncSessionLocal() as session:
        doc_repo = DocumentRepository(session)
        try:
            doc = await doc_repo.find_by_document_id(document_id)
            if not doc:
                bound_log.error("document not found")
                return

            doc_id = doc["id"]
            extracted = doc.get("extracted") or {}

            customer_raw = await _fetch_customer(session, customer_id)
            if not customer_raw:
                bound_log.error("customer not found", customer_id=customer_id)
                return

            payload_dict = _build_so_payload(extracted, customer_raw)
            payload = SOPayload(**payload_dict)

            await doc_repo.update_status(doc_id, DocumentStatus.POSTING)
            await session.commit()

            sap = get_sap_service()
            result = await sap.create_sales_order(payload)

            bound_log.info("SO create response",
                           sales_order=result.sales_order_number,
                           success=result.success)

            return_msgs = result.sap_response.get("RETURN") or []
            so_posting = {
                "posted_at":          datetime.now(UTC).isoformat(),
                "payload_sent":       payload_dict,
                "sales_order_number": result.sales_order_number,
                "sap_response":       result.sap_response,
                "return_messages":    return_msgs,
                "errors":             [m for m in return_msgs if m.get("TYPE") == "E"],
                "warnings":           [m for m in return_msgs if m.get("TYPE") == "W"],
                "successes":          [m for m in return_msgs if m.get("TYPE") == "S"],
                "status":             "success" if result.success else "failed",
                "message":            result.message,
            }

            new_status = DocumentStatus.POSTED.value if result.success else DocumentStatus.VALIDATED.value
            await doc_repo.update(doc_id, {"so_posting": so_posting, "status": new_status})
            await session.commit()
            bound_log.info("SO create saved", status=so_posting["status"])

        except Exception as exc:
            bound_log.error("SO create exception", error=str(exc), traceback=_tb.format_exc())
            try:
                doc2 = await doc_repo.find_by_document_id(document_id)
                if doc2:
                    await doc_repo.update(doc2["id"], {
                        "status": DocumentStatus.VALIDATED.value,
                        "so_posting": {
                            "status":     "failed",
                            "message":    str(exc),
                            "sap_response": {},
                            "posted_at":  datetime.now(UTC).isoformat(),
                        },
                    })
                    await session.commit()
            except Exception:
                pass
