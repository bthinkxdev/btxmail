import logging
import time
from datetime import timedelta

from celery import shared_task
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit import service as audit
from apps.domains.models import Domain
from apps.mailcow import mailboxes as mc_mailboxes
from apps.mailcow.client import get_client
from apps.mailcow.exceptions import MailcowError
from apps.notifications.service import raise_alert

from .models import Mailbox
from .services import desired_remote_state

logger = logging.getLogger(__name__)

RETRY_COUNTDOWNS = (30, 120, 600)
IMPORT_GRACE_SECONDS = 10 * 60
SYNC_LOCK_KEY = "lock:sync_mailcow"

_STATE_FROM_REMOTE = {
    mc_mailboxes.ACTIVE: Mailbox.Status.ACTIVE,
    mc_mailboxes.LOGIN_DISALLOWED: Mailbox.Status.SUSPENDED,
    mc_mailboxes.INACTIVE: Mailbox.Status.DISABLED,
}


def _seen_long_enough(email: str) -> bool:
    """Only import unknown remote mailboxes after they've existed for a grace period
    (avoids racing an in-flight create from the portal)."""
    key = f"sync:first-seen:{email}"
    first_seen = cache.get(key)
    now = time.time()
    if first_seen is None:
        cache.set(key, now, IMPORT_GRACE_SECONDS * 6)
        return False
    return now - float(first_seen) >= IMPORT_GRACE_SECONDS


@shared_task(acks_late=True)
def sync_mailcow() -> dict:
    """
    Reconcile Django with Mailcow:
      * refresh usage / login data for every mailbox,
      * push Django's desired state where Mailcow drifted (Django owns business state),
      * flag mailboxes that vanished from Mailcow,
      * import mailboxes created directly in Mailcow on platform-managed domains.
    """
    if not cache.add(SYNC_LOCK_KEY, "1", timeout=600):
        return {"skipped": "another sync is running"}
    stats = {"updated": 0, "drift_fixed": 0, "missing": 0, "imported": 0, "errors": 0}
    try:
        client = get_client()
        remote = {}
        for raw in mc_mailboxes.list_mailboxes(client):
            parsed = mc_mailboxes.parse_mailbox(raw)
            if parsed["username"]:
                remote[parsed["username"]] = parsed

        now = timezone.now()

        # A worker that died mid-provisioning leaves a PENDING reservation behind. Finish it if
        # the mailbox exists on Mailcow, otherwise release the quota it holds.
        for stale in Mailbox.objects.filter(
            status=Mailbox.Status.PENDING, updated_at__lt=now - timedelta(seconds=IMPORT_GRACE_SECONDS)
        ):
            if stale.email.lower() in remote:
                Mailbox.objects.filter(pk=stale.pk).update(status=Mailbox.Status.ACTIVE, mailcow_id=stale.email)
            else:
                stale.delete()

        known_emails = set(Mailbox.objects.values_list("email", flat=True))

        for mailbox in Mailbox.objects.exclude(
            status__in=[Mailbox.Status.PENDING, Mailbox.Status.DELETING]
        ).select_related("business__plan", "domain"):
            r = remote.get(mailbox.email.lower())
            if r is None:
                if mailbox.status != Mailbox.Status.FAILED:
                    Mailbox.objects.filter(pk=mailbox.pk).update(
                        status=Mailbox.Status.FAILED,
                        last_error="Mailbox not found on the mail server.",
                        last_synced_at=now,
                    )
                    audit.record("sync.mailbox_missing", business=mailbox.business, obj=mailbox)
                    raise_alert(
                        f"mailbox-missing:{mailbox.email}",
                        f"Mailbox missing on Mailcow: {mailbox.email}",
                        f"{mailbox.email} ({mailbox.business.name}) exists in the platform but not on Mailcow.",
                        severity="CRITICAL",
                        business=mailbox.business,
                    )
                stats["missing"] += 1
                continue

            fields = {
                "used_bytes": r["used_bytes"],
                "message_count": r["messages"],
                "last_synced_at": now,
            }
            if r["last_login_at"]:
                fields["last_login_at"] = r["last_login_at"]
            if mailbox.status == Mailbox.Status.FAILED:
                fields["status"] = _STATE_FROM_REMOTE.get(r["active"], Mailbox.Status.ACTIVE)
                fields["last_error"] = ""
                mailbox.status = fields["status"]
            Mailbox.objects.filter(pk=mailbox.pk).update(**fields)
            stats["updated"] += 1

            try:
                drift = {}
                desired = desired_remote_state(mailbox)
                if r["active"] != desired:
                    mc_mailboxes.set_active_state(mailbox.email, desired, client)
                    drift["active"] = {"remote": r["active"], "desired": desired}
                if r["smtp_access"] == mailbox.outbound_suspended:
                    mc_mailboxes.set_smtp_access(mailbox.email, not mailbox.outbound_suspended, client)
                    drift["smtp_access"] = {"remote": r["smtp_access"], "desired": not mailbox.outbound_suspended}
                if r["quota_bytes"] and r["quota_bytes"] != mailbox.quota_bytes:
                    mc_mailboxes.edit_mailbox(mailbox.email, {"quota": str(mailbox.quota_mb)}, client)
                    drift["quota_bytes"] = {"remote": r["quota_bytes"], "desired": mailbox.quota_bytes}
                if drift:
                    stats["drift_fixed"] += 1
                    audit.record("sync.drift_corrected", business=mailbox.business, obj=mailbox, metadata=drift)
            except MailcowError as exc:
                stats["errors"] += 1
                logger.warning("Could not correct drift for %s: %s", mailbox.email, exc.message)

        managed = {d.name: d for d in Domain.objects.filter(mailcow_provisioned=True).select_related("business__plan")}
        for email, r in remote.items():
            if email in known_emails or "@" not in email:
                continue
            local, domain_name = email.split("@", 1)
            domain = managed.get(domain_name)
            if domain is None or not _seen_long_enough(email):
                continue
            quota_mb = (
                max(r["quota_bytes"] // (1024 * 1024), 1)
                if r["quota_bytes"]
                else domain.business.plan.default_mailbox_quota_mb
            )
            try:
                with transaction.atomic():
                    mailbox = Mailbox.objects.create(
                        business=domain.business,
                        domain=domain,
                        local_part=local,
                        email=email,
                        display_name=r["name"][:200],
                        quota_mb=quota_mb,
                        status=_STATE_FROM_REMOTE.get(r["active"], Mailbox.Status.ACTIVE),
                        outbound_suspended=not r["smtp_access"],
                        used_bytes=r["used_bytes"],
                        message_count=r["messages"],
                        last_login_at=r["last_login_at"],
                        mailcow_id=email,
                        last_synced_at=now,
                    )
            except IntegrityError:
                continue
            stats["imported"] += 1
            audit.record("sync.mailbox_imported", business=domain.business, obj=mailbox)
            raise_alert(
                f"mailbox-imported:{email}",
                f"Mailbox created outside the portal: {email}",
                f"{email} was found on Mailcow and imported into {domain.business.name}. Verify it was intended.",
                business=domain.business,
            )
        return stats
    finally:
        cache.delete(SYNC_LOCK_KEY)


@shared_task(bind=True, max_retries=len(RETRY_COUNTDOWNS))
def apply_business_state_task(self, business_id: int) -> str:
    """Push login-allowed/disallowed state to every mailbox after a business status change."""
    client = get_client()
    failures = []
    for mailbox in Mailbox.objects.filter(
        business_id=business_id,
        status__in=[Mailbox.Status.ACTIVE, Mailbox.Status.SUSPENDED, Mailbox.Status.DISABLED],
    ).select_related("business"):
        try:
            mc_mailboxes.set_active_state(mailbox.email, desired_remote_state(mailbox), client)
        except MailcowError as exc:
            failures.append(f"{mailbox.email}: {exc.message}")
    if failures:
        if self.request.retries < len(RETRY_COUNTDOWNS):
            raise self.retry(countdown=RETRY_COUNTDOWNS[self.request.retries])
        raise_alert(
            f"business-state:{business_id}",
            "Could not apply business status to all mailboxes",
            "\n".join(failures),
            severity="CRITICAL",
        )
        return "failed"
    return "ok"


@shared_task(bind=True, max_retries=len(RETRY_COUNTDOWNS))
def push_rate_limits_task(self, business_id: int) -> str:
    client = get_client()
    failures = []
    for mailbox in Mailbox.objects.filter(
        business_id=business_id,
        status__in=[Mailbox.Status.ACTIVE, Mailbox.Status.SUSPENDED, Mailbox.Status.DISABLED],
    ).select_related("business__plan"):
        try:
            mc_mailboxes.set_rate_limit(mailbox.email, mailbox.effective_hourly_limit(), client)
        except MailcowError as exc:
            failures.append(f"{mailbox.email}: {exc.message}")
    if failures:
        if self.request.retries < len(RETRY_COUNTDOWNS):
            raise self.retry(countdown=RETRY_COUNTDOWNS[self.request.retries])
        raise_alert(f"rate-limits:{business_id}", "Could not apply outbound rate limits", "\n".join(failures))
        return "failed"
    return "ok"
