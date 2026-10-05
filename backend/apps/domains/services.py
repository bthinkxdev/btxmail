"""
Domain lifecycle:

PENDING_VERIFICATION ──(TXT verified)──▶ PROVISIONING ──(Mailcow domain + DKIM)──▶ DNS_PENDING
        ▲                                     │                                         │
        │                         (retries exhausted)                          (MX+SPF+DKIM pass)
        │                                     ▼                                         ▼
        │                           PROVISIONING_FAILED                               ACTIVE
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit import service as audit
from apps.core.exceptions import Conflict, QuotaExceeded, ServiceError
from apps.mailcow import dkim as mc_dkim
from apps.mailcow import domains as mc_domains
from apps.mailcow.client import get_client
from apps.mailcow.exceptions import MailcowError
from apps.notifications.service import raise_alert

from . import dns_checks
from .models import Domain, DomainDNSStatus

logger = logging.getLogger(__name__)


def mailcow_limits_for(plan) -> dict:
    max_q = plan.max_mailbox_quota_mb
    return {
        "max_mailboxes": plan.max_mailboxes,
        "default_quota_mb": min(plan.default_mailbox_quota_mb, max_q),
        "max_quota_mb": max_q,
        "total_quota_mb": max(plan.total_storage_mb, max_q),
        "max_aliases": plan.max_aliases,
    }


# --------------------------------------------------------------------------- #
# Creation & verification
# --------------------------------------------------------------------------- #
def create_domain(*, business, name: str, actor=None, request=None) -> Domain:
    try:
        normalized = dns_checks.normalize_domain(name)
    except ValueError as exc:
        raise ServiceError(str(exc)) from exc

    if not business.is_active:
        raise ServiceError("This business is not active.")

    with transaction.atomic():
        type(business).objects.select_for_update().get(pk=business.pk)
        if Domain.objects.filter(name=normalized).exists():
            raise Conflict("This domain is already registered on the platform.")
        if business.domains.exclude(status=Domain.Status.DELETING).count() >= business.plan.max_domains:
            raise QuotaExceeded(f"Your plan allows at most {business.plan.max_domains} domain(s).")
        try:
            domain = Domain.objects.create(business=business, name=normalized)
        except IntegrityError as exc:
            raise Conflict("This domain is already registered on the platform.") from exc
        DomainDNSStatus.objects.create(domain=domain)
        audit.record("domain.created", actor=actor, request=request, business=business, obj=domain)
    return domain


def verification_expired(domain: Domain) -> bool:
    return domain.verification_started_at < timezone.now() - timedelta(days=settings.DOMAIN_VERIFICATION_EXPIRY_DAYS)


def regenerate_verification_token(domain: Domain, *, actor=None, request=None) -> Domain:
    from .models import generate_verification_token

    if domain.status != Domain.Status.PENDING_VERIFICATION:
        raise ServiceError("Only domains awaiting verification can get a new token.")
    domain.verification_token = generate_verification_token()
    domain.verification_started_at = timezone.now()  # restart the verification window
    domain.save(update_fields=["verification_token", "verification_started_at", "updated_at"])
    audit.record("domain.token_regenerated", actor=actor, request=request, business=domain.business, obj=domain)
    return domain


def verify_domain(domain: Domain, *, actor=None, request=None) -> dns_checks.CheckResult:
    """Check the ownership TXT record; on success queue Mailcow provisioning."""
    if domain.status != Domain.Status.PENDING_VERIFICATION:
        return dns_checks.CheckResult(dns_checks.PASS, "Domain is already verified.")

    result = dns_checks.check_verification(domain.name, domain.verification_token)
    with transaction.atomic():
        locked = Domain.objects.select_for_update().get(pk=domain.pk)
        locked.last_verification_attempt_at = timezone.now()
        if result.status == dns_checks.PASS and locked.status == Domain.Status.PENDING_VERIFICATION:
            locked.status = Domain.Status.PROVISIONING
            locked.verified_at = timezone.now()
            locked.verification_method = Domain.VerificationMethod.DNS_TXT
            locked.last_error = ""
            locked.save()
            audit.record("domain.verified", actor=actor, request=request, business=locked.business, obj=locked)
            _queue_provisioning(locked.pk)
        else:
            locked.save(update_fields=["last_verification_attempt_at", "updated_at"])
    domain.refresh_from_db()
    return result


def mark_verified_manually(domain: Domain, *, actor, request=None, reason: str = "") -> Domain:
    """Staff override when a customer cannot publish TXT records (documented in audit)."""
    with transaction.atomic():
        locked = Domain.objects.select_for_update().get(pk=domain.pk)
        if locked.status != Domain.Status.PENDING_VERIFICATION:
            raise ServiceError("Domain is not awaiting verification.")
        locked.status = Domain.Status.PROVISIONING
        locked.verified_at = timezone.now()
        locked.verification_method = Domain.VerificationMethod.MANUAL
        locked.save()
        audit.record(
            "domain.verified_manually",
            actor=actor,
            request=request,
            business=locked.business,
            obj=locked,
            metadata={"reason": reason},
        )
        _queue_provisioning(locked.pk)
    domain.refresh_from_db()
    return domain


def _queue_provisioning(domain_id: int) -> None:
    from .tasks import provision_domain_task

    transaction.on_commit(lambda: provision_domain_task.delay(domain_id))


def retry_provisioning(domain: Domain, *, actor=None, request=None) -> Domain:
    with transaction.atomic():
        locked = Domain.objects.select_for_update().get(pk=domain.pk)
        if locked.status != Domain.Status.PROVISIONING_FAILED:
            raise ServiceError("Only domains whose provisioning failed can be retried.")
        locked.status = Domain.Status.PROVISIONING
        locked.provisioning_attempts = 0
        locked.last_error = ""
        locked.save()
        audit.record("domain.provisioning_retried", actor=actor, request=request, business=locked.business, obj=locked)
        _queue_provisioning(locked.pk)
    domain.refresh_from_db()
    return domain


# --------------------------------------------------------------------------- #
# Provisioning (runs in Celery)
# --------------------------------------------------------------------------- #
def provision_domain(domain_id: int) -> Domain | None:
    """
    Idempotently create the domain + DKIM key in Mailcow.
    Raises MailcowError so the Celery task can apply its retry policy.
    """
    with transaction.atomic():
        domain = Domain.objects.select_for_update().select_related("business__plan").filter(pk=domain_id).first()
        if domain is None or domain.status not in (Domain.Status.PROVISIONING,):
            return domain
        domain.provisioning_attempts += 1
        domain.save(update_fields=["provisioning_attempts", "updated_at"])

    client = get_client()
    plan = domain.business.plan
    try:
        mc_domains.create_domain(
            domain.name,
            description=f"{domain.business.name} (btx#{domain.business_id})",
            rate_limit_per_hour=plan.outbound_per_hour * max(plan.max_mailboxes, 1),
            client=client,
            **mailcow_limits_for(plan),
        )
        key = mc_dkim.ensure_dkim(
            domain.name, selector=settings.DKIM_SELECTOR, key_size=settings.DKIM_KEY_SIZE, client=client
        )
    except MailcowError as exc:
        Domain.objects.filter(pk=domain.pk).update(last_error=exc.message[:2000], updated_at=timezone.now())
        raise

    with transaction.atomic():
        domain = Domain.objects.select_for_update().get(pk=domain_id)
        domain.mailcow_provisioned = True
        domain.dkim_selector = key.get("dkim_selector") or settings.DKIM_SELECTOR
        domain.dkim_public_record = key.get("dkim_txt", "")
        domain.status = Domain.Status.DNS_PENDING
        domain.last_error = ""
        domain.save()
        audit.record("domain.provisioned", business=domain.business, obj=domain)
    refresh_dns_status(domain)
    return domain


def mark_provisioning_failed(domain_id: int, error: str) -> None:
    domain = Domain.objects.select_related("business").filter(pk=domain_id).first()
    if domain is None:
        return
    Domain.objects.filter(pk=domain_id, status=Domain.Status.PROVISIONING).update(
        status=Domain.Status.PROVISIONING_FAILED, last_error=error[:2000], updated_at=timezone.now()
    )
    audit.record("domain.provisioning_failed", business=domain.business, obj=domain, metadata={"error": error[:500]})
    raise_alert(
        f"domain-provision-failed:{domain_id}",
        f"Domain provisioning failed: {domain.name}",
        f"Provisioning {domain.name} for {domain.business.name} failed after retries.\nLast error: {error}",
        severity="CRITICAL",
        business=domain.business,
    )


# --------------------------------------------------------------------------- #
# DNS health
# --------------------------------------------------------------------------- #
def refresh_dns_status(domain: Domain) -> DomainDNSStatus:
    status, _ = DomainDNSStatus.objects.get_or_create(domain=domain)
    previously_ready = status.is_ready

    mx = dns_checks.check_mx(domain.name)
    spf = dns_checks.check_spf(domain.name)
    dkim = dns_checks.check_dkim(domain.name, domain.dkim_selector or settings.DKIM_SELECTOR, domain.dkim_public_record)
    dmarc = dns_checks.check_dmarc(domain.name)
    ptr = dns_checks.check_ptr()

    status.mx_status = mx.status
    status.spf_status = spf.status
    status.dkim_status = dkim.status
    status.dmarc_status = dmarc.status
    status.ptr_status = ptr.status
    status.details = {
        "mx": mx.as_dict(),
        "spf": spf.as_dict(),
        "dkim": dkim.as_dict(),
        "dmarc": dmarc.as_dict(),
        "ptr": ptr.as_dict(),
    }
    status.last_checked = timezone.now()
    status.save()

    if status.is_ready and domain.status == Domain.Status.DNS_PENDING:
        Domain.objects.filter(pk=domain.pk, status=Domain.Status.DNS_PENDING).update(
            status=Domain.Status.ACTIVE, updated_at=timezone.now()
        )
        domain.status = Domain.Status.ACTIVE
        audit.record("domain.activated", business=domain.business, obj=domain)
    elif previously_ready and domain.status == Domain.Status.ACTIVE:
        failing = [n for n, r in (("MX", mx), ("SPF", spf), ("DKIM", dkim)) if r.status == dns_checks.FAIL]
        if failing:
            raise_alert(
                f"dns-failure:{domain.pk}:{'-'.join(failing)}",
                f"DNS problem on {domain.name}",
                f"{', '.join(failing)} checks are failing for {domain.name} ({domain.business.name}).",
                business=domain.business,
            )
    return status


# --------------------------------------------------------------------------- #
# Suspension / deletion / plan changes
# --------------------------------------------------------------------------- #
def set_domain_suspended(domain: Domain, suspended: bool, *, actor, request=None) -> Domain:
    if not domain.mailcow_provisioned:
        raise ServiceError("Domain is not provisioned on the mail server yet.")
    target = Domain.Status.SUSPENDED if suspended else None
    if suspended and domain.status == Domain.Status.SUSPENDED:
        return domain
    if not suspended and domain.status != Domain.Status.SUSPENDED:
        return domain
    mc_domains.set_domain_active(domain.name, not suspended)
    if target is None:
        dns_ready = hasattr(domain, "dns_status") and domain.dns_status.is_ready
        target = Domain.Status.ACTIVE if dns_ready else Domain.Status.DNS_PENDING
    domain.status = target
    domain.save(update_fields=["status", "updated_at"])
    audit.record(
        "domain.suspended" if suspended else "domain.reactivated",
        actor=actor,
        request=request,
        business=domain.business,
        obj=domain,
    )
    return domain


def delete_domain(domain: Domain, *, actor, request=None) -> None:
    if domain.mailboxes.exists() or domain.aliases.exists():
        raise Conflict("Delete all mailboxes and aliases on this domain first.")
    if domain.status == Domain.Status.PROVISIONING:
        raise Conflict("Domain is being provisioned; try again in a few minutes.")

    previous_status = domain.status
    Domain.objects.filter(pk=domain.pk).update(status=Domain.Status.DELETING)
    if domain.mailcow_provisioned:
        try:
            client = get_client()
            mc_domains.delete_domain(domain.name, client)
            mc_dkim.delete_dkim(domain.name, client)
        except MailcowError:
            Domain.objects.filter(pk=domain.pk).update(status=previous_status)
            raise
    business, name = domain.business, domain.name
    domain.delete()
    audit.record("domain.deleted", actor=actor, request=request, business=business, metadata={"domain": name})


def apply_plan_limits(business) -> list[str]:
    """Push the business plan's limits onto every provisioned domain. Returns errors."""
    errors = []
    limits = mailcow_limits_for(business.plan)
    client = get_client()
    for domain in business.domains.filter(mailcow_provisioned=True):
        try:
            mc_domains.update_domain_limits(domain.name, client=client, **limits)
        except MailcowError as exc:
            errors.append(f"{domain.name}: {exc.message}")
    return errors
