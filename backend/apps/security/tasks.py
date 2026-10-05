import logging

from celery import shared_task
from django.core.cache import cache

from apps.mailcow.exceptions import MailcowError

from . import services

logger = logging.getLogger(__name__)


@shared_task(acks_late=True)
def detect_abuse() -> dict:
    if not cache.add("lock:detect_abuse", "1", timeout=600):
        return {"skipped": "already running"}
    try:
        return services.detect_abuse()
    except MailcowError as exc:
        logger.error("Abuse detection could not read Mailcow logs: %s", exc.message)
        from apps.notifications.service import raise_alert

        raise_alert(
            "abuse-detection-unavailable",
            "Abuse detection cannot read Mailcow logs",
            f"Outbound abuse monitoring is blind until this is fixed: {exc.message}",
            severity="CRITICAL",
        )
        return {"error": exc.message}
    finally:
        cache.delete("lock:detect_abuse")
