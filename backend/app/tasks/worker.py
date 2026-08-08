"""Celery app instance with task configuration."""

from __future__ import annotations

from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "knowledge_drift",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,

    # ── Result backend (Change 6) ──
    result_extended=True,           # store task name, args, kwargs in result
    result_expires=604800,          # 7 days TTL
    database_short_lived_sessions=True,  # close DB connections after each result write

    # Single-worker setup: all tasks go to default queue.
    task_default_queue="celery",
    worker_direct=False,
)

# Auto-discover tasks
celery_app.autodiscover_tasks(["app.tasks"])
