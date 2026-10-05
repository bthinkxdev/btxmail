from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from . import services
from .models import BlacklistCheck, HealthCheck


@shared_task
def check_mailcow_health():
    return services.check_mailcow_health()


@shared_task
def check_blacklists():
    return services.check_blacklists()


@shared_task
def check_backup_freshness():
    return services.check_backup_freshness()


@shared_task
def prune_old_records() -> dict:
    from apps.audit.models import AuditLog
    from apps.notifications.models import Alert

    now = timezone.now()
    health_cutoff = now - timedelta(days=settings.HEALTH_RETENTION_DAYS)
    deleted = {
        # keep backup reports for the full audit window so freshness history survives
        "health": HealthCheck.objects.filter(checked_at__lt=health_cutoff).exclude(component="backup").delete()[0],
        "blacklist": BlacklistCheck.objects.filter(checked_at__lt=health_cutoff).delete()[0],
        "alerts": Alert.objects.filter(created_at__lt=now - timedelta(days=180)).delete()[0],
        "audit": AuditLog.objects.filter(timestamp__lt=now - timedelta(days=settings.AUDIT_RETENTION_DAYS)).delete()[0],
    }
    return deleted
