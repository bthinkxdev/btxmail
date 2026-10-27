"""
Operational alerting for BThinkX administrators.

`raise_alert()` persists the alert (deduplicated by key within
ALERT_DEDUP_SECONDS) and delivers it by e-mail and/or webhook through Celery.

If called inside a database transaction that may roll back (e.g. a failed
provisioning attempt), the alert is handed to Celery immediately so it is
not lost with the rollback.
"""

import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import Alert

logger = logging.getLogger(__name__)


def _store_alert(key, title, message, severity, business_id) -> Alert | None:
    window_start = timezone.now() - timedelta(seconds=settings.ALERT_DEDUP_SECONDS)
    if Alert.objects.filter(key=key, created_at__gte=window_start).exists():
        logger.info("Alert %s suppressed (dedup window)", key)
        return None
    alert = Alert.objects.create(
        key=key[:200], title=title[:255], message=message, severity=severity, business_id=business_id
    )
    logger.warning("ALERT [%s] %s — %s", severity, title, message)
    return alert


def raise_alert(key: str, title: str, message: str, *, severity=Alert.Severity.WARNING, business=None) -> Alert | None:
    from .tasks import deliver_alert, push_alert, store_and_deliver_alert

    business_id = getattr(business, "pk", None)
    severity = str(severity)
    if transaction.get_connection().in_atomic_block:
        store_and_deliver_alert.delay(key, title, message, severity, business_id)
        return None
    alert = _store_alert(key, title, message, severity, business_id)
    if alert is not None:
        deliver_alert.delay(alert.pk)
        push_alert.delay(alert.pk)
    return alert
