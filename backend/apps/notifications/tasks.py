import logging

import requests
from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail

from .models import Alert

logger = logging.getLogger(__name__)


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=30, retry_backoff_max=600, max_retries=5)
def deliver_alert(self, alert_id: int) -> str:
    """Deliver an alert to every configured channel; each channel is sent at most once."""
    alert = Alert.objects.filter(pk=alert_id).first()
    if alert is None or alert.delivered:
        return "skipped"

    subject = f"[{settings.PLATFORM_NAME}] [{alert.severity}] {alert.title}"
    done = set(alert.channels_delivered or [])
    errors = []

    if settings.ALERT_EMAILS and "email" not in done:
        try:
            send_mail(subject, alert.message, settings.DEFAULT_FROM_EMAIL, settings.ALERT_EMAILS, fail_silently=False)
            done.add("email")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"email: {exc}")

    if settings.ALERT_WEBHOOK_URL and "webhook" not in done:
        try:
            resp = requests.post(
                settings.ALERT_WEBHOOK_URL,
                json={
                    "text": f"*{subject}*\n{alert.message}",
                    "severity": alert.severity,
                    "title": alert.title,
                    "message": alert.message,
                    "key": alert.key,
                },
                timeout=10,
            )
            resp.raise_for_status()
            done.add("webhook")
        except requests.RequestException as exc:
            errors.append(f"webhook: {exc}")

    if not settings.ALERT_EMAILS and not settings.ALERT_WEBHOOK_URL:
        logger.warning("No ALERT_EMAILS or ALERT_WEBHOOK_URL configured; alert %s only stored.", alert.pk)

    alert.channels_delivered = sorted(done)
    alert.delivery_error = "; ".join(errors)[:2000]
    alert.delivered = not errors
    alert.save(update_fields=["channels_delivered", "delivery_error", "delivered"])
    if errors:
        raise RuntimeError(alert.delivery_error)
    return "delivered"


@shared_task
def store_and_deliver_alert(key: str, title: str, message: str, severity: str, business_id: int | None = None):
    from .service import _store_alert

    alert = _store_alert(key, title, message, severity, business_id)
    if alert is not None:
        deliver_alert.delay(alert.pk)
    return alert.pk if alert else None
