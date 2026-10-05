import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from apps.mailcow.exceptions import MailcowError

from . import services
from .models import Domain

logger = logging.getLogger(__name__)

# Retry schedule from the spec: 30s → 2min → 10min → dead-letter + admin alert.
RETRY_COUNTDOWNS = (30, 120, 600)


@shared_task(bind=True, max_retries=len(RETRY_COUNTDOWNS), acks_late=True)
def provision_domain_task(self, domain_id: int) -> str:
    try:
        domain = services.provision_domain(domain_id)
    except MailcowError as exc:
        if self.request.retries < len(RETRY_COUNTDOWNS):
            countdown = RETRY_COUNTDOWNS[self.request.retries]
            logger.warning("Provisioning domain %s failed (%s); retrying in %ss", domain_id, exc.message, countdown)
            raise self.retry(exc=exc, countdown=countdown) from exc
        services.mark_provisioning_failed(domain_id, exc.message)
        return "failed"
    return domain.status if domain else "missing"


@shared_task
def verify_pending_domains() -> int:
    verified = 0
    for domain in Domain.objects.filter(status=Domain.Status.PENDING_VERIFICATION).select_related("business"):
        if services.verification_expired(domain):
            continue
        try:
            result = services.verify_domain(domain)
        except Exception:  # noqa: BLE001 - one bad domain must not stop the batch
            logger.exception("Verification failed for %s", domain.name)
            continue
        if result.status == "PASS":
            verified += 1
    return verified


@shared_task
def refresh_domain_dns_task(domain_id: int) -> str:
    domain = Domain.objects.select_related("business").filter(pk=domain_id).first()
    if domain is None or not domain.mailcow_provisioned:
        return "skipped"
    services.refresh_dns_status(domain)
    return "ok"


@shared_task
def check_all_dns_records() -> int:
    count = 0
    qs = Domain.objects.filter(
        mailcow_provisioned=True, status__in=[Domain.Status.DNS_PENDING, Domain.Status.ACTIVE]
    ).select_related("business")
    for domain in qs:
        try:
            services.refresh_dns_status(domain)
            count += 1
        except Exception:  # noqa: BLE001
            logger.exception("DNS check failed for %s", domain.name)
    return count


@shared_task
def retry_failed_provisioning() -> int:
    """Re-queue domains stuck in PROVISIONING (e.g. worker died mid-task)."""
    stale = timezone.now() - timedelta(minutes=20)
    ids = list(
        Domain.objects.filter(status=Domain.Status.PROVISIONING, updated_at__lt=stale).values_list("pk", flat=True)
    )
    for domain_id in ids:
        provision_domain_task.delay(domain_id)
    return len(ids)


@shared_task(bind=True, max_retries=len(RETRY_COUNTDOWNS))
def apply_plan_limits_task(self, business_id: int) -> str:
    from apps.businesses.models import Business

    business = Business.objects.select_related("plan").filter(pk=business_id).first()
    if business is None:
        return "missing"
    errors = services.apply_plan_limits(business)
    if errors:
        if self.request.retries < len(RETRY_COUNTDOWNS):
            raise self.retry(countdown=RETRY_COUNTDOWNS[self.request.retries])
        from apps.notifications.service import raise_alert

        raise_alert(
            f"plan-limits:{business_id}",
            f"Could not apply plan limits for {business.name}",
            "\n".join(errors),
            business=business,
        )
        return "failed"
    return "ok"
