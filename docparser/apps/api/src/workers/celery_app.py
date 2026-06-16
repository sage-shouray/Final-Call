"""Celery application configuration.

Broker  → Redis DB 1  (task queue)
Backend → Redis DB 2  (result storage)

Task queues
-----------
  ocr_queue  — document extraction tasks
  sap_queue  — SAP integration tasks (future)
  default    — everything else

Beat schedule
-------------
  cleanup_failed_documents — runs at midnight UTC every day
"""
from celery import Celery
from celery.schedules import crontab

from src.config import settings

celery_app = Celery(
    "docparser",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "src.workers.ocr_worker",
        "src.workers.sap_worker",
    ],
)

celery_app.conf.update(
    # Serialisation
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    # Results
    result_expires=3600,             # discard task results after 1 hour
    result_extended=True,            # store task metadata (name, args, kwargs)
    # Execution
    task_acks_late=True,             # ack only after task completes — safe retry on worker crash
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,    # one task at a time per worker process
    # Retries
    task_max_retries=3,
    # Routing
    task_routes={
        "extract_document":           {"queue": "ocr_queue"},
        "validate_document":          {"queue": "sap_queue"},
        "post_miro_document":         {"queue": "sap_queue"},
        "cleanup_failed_documents":   {"queue": "default"},
    },
    task_default_queue="default",
    task_queues={
        "default":   {"exchange": "default"},
        "ocr_queue": {"exchange": "ocr"},
        "sap_queue": {"exchange": "sap"},
    },
    # Beat
    beat_schedule={
        "cleanup-failed-documents": {
            "task": "cleanup_failed_documents",
            "schedule": crontab(hour=0, minute=0),  # midnight UTC
        },
    },
    beat_schedule_filename="celerybeat-schedule",
    timezone="UTC",
)
