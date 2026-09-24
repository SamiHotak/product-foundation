"""Celery application.

Start a worker:  celery -A app.workers.celery_app worker --loglevel=INFO
Start beat:      celery -A app.workers.celery_app beat --loglevel=INFO
"""

from typing import Any

from celery import Celery
from celery.signals import setup_logging

from app.core.config import get_settings
from app.core.logging import configure_logging

settings = get_settings()

celery_app = Celery(
    "product_foundation",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # Job status and results are stored in Postgres (jobs table), so Celery keeps none.
    task_ignore_result=True,
    # Reliability: ack after the task finishes, so a crashed worker's task is retried.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_time_limit=15 * 60,
    task_soft_time_limit=14 * 60,
    broker_connection_retry_on_startup=True,
    beat_schedule={
        "heartbeat-every-5-minutes": {
            "task": "app.workers.tasks.heartbeat",
            "schedule": 5 * 60.0,
        },
    },
)


@setup_logging.connect  # type: ignore[untyped-decorator]
def _setup_logging(**_kwargs: Any) -> None:
    """Use our structured logging in workers instead of Celery's default."""
    configure_logging(settings.log_level, settings.log_format)
