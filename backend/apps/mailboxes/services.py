"""
Mailbox and alias lifecycle.

Every mutation follows the same pattern:
  1. lock the business row (serialises quota checks per tenant),
  2. validate business rules,
  3. call Mailcow,
  4. persist; on any failure after the remote call succeeded, compensate
     (undo the remote change) so no half-created objects remain.

Mailbox passwords are generated here, sent to Mailcow and returned to the
caller exactly once. They are never stored in the platform database.
"""

from __future__ import annotations

import logging
import re

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.utils import timezone

from apps.audit import service as audit
from apps.businesses.models import Business
from apps.core.exceptions import Conflict, QuotaExceeded, ServiceError
from apps.core.utils import generate_password
from apps.domains.models import Domain
from apps.mailcow import aliases as mc_aliases
from apps.mailcow import mailboxes as mc_mailboxes
from apps.mailcow.client import get_client
from apps.mailcow.errors import raise_conflict_or_reraise
from apps.mailcow.exceptions import MailcowError
from apps.notifications.service import raise_alert

from .models import Alias, Mailbox

logger = logging.getLogger(__name__)

LOCAL_PART_RE = re.compile(r"^[a-z0-9](?:[a-z0-9._+-]{0,62}[a-z0-9])?$")
RESERVED_LOCAL_PARTS = {"postmaster", "abuse", "mailer-daemon"}
MAX_ALIAS_DESTINATIONS = 20


# --------------------------------------------------------------------------- #
# Validation helpers
# --------------------------------------------------------------------------- #
def normalize_local_part(value: str, *, allow_reserved: bool = False) -> str:
    local = (value or "").strip().lower()
    if not LOCAL_PART_RE.match(local) or ".." in local:
        raise ServiceError(
            "Use 1–64 letters, digits, dots, hyphens, underscores or plus signs; "
            "it must start and end with a letter or digit."
        )
    if local in RESERVED_LOCAL_PARTS and not allow_reserved:
        raise ServiceError(f"'{local}' is reserved. Create it as an alias instead.")
    return local


def _require_mail_domain(domain: Domain, business: Business) -> None:
    if domain.business_id != business.pk:
        raise ServiceError("Domain does not belong to this business.")
    if not business.is_active:
        raise ServiceError("This business is suspended.")
    if domain.status == Domain.Status.SUSPENDED:
        raise ServiceError("This domain is suspended.")
    if not domain.is_provisioned:
        raise ServiceError("This domain is not ready yet. Verify it and wait for provisioning to finish.")


def _address_taken(address: str, *, exclude_alias_id=None) -> bool:
    if Mailbox.objects.filter(email__iexact=address).exists():
        return True
    qs = Alias.objects.filter(source_address__iexact=address)
    if exclude_alias_id:
        qs = qs.exclude(pk=exclude_alias_id)
    return qs.exists()


def _lock_business(business: Business) -> Business:
    return Business.objects.select_for_update().select_related("plan").get(pk=business.pk)


def _validate_quota(business: Business, quota_mb: int, *, exclude_mailbox_id=None) -> None:
    plan = business.plan
    if quota_mb < 1:
        raise ServiceError("Quota must be at least 1 MB.")
    if quota_mb > plan.max_mailbox_quota_mb:
        raise QuotaExceeded(f"Your plan allows at most {plan.max_mailbox_quota_mb} MB per mailbox.")
    allocated = business.allocated_storage_mb(exclude_mailbox_id=exclude_mailbox_id)
    if allocated + quota_mb > plan.total_storage_mb:
        remaining = max(plan.total_storage_mb - allocated, 0)
        raise QuotaExceeded(f"Not enough storage left in your plan ({remaining} MB unallocated).")


def desired_remote_state(mailbox: Mailbox) -> str:
    """Mailcow `active` value the platform wants for this mailbox."""
    if mailbox.status == Mailbox.Status.DISABLED:
        return mc_mailboxes.INACTIVE
    if mailbox.status == Mailbox.Status.SUSPENDED or not mailbox.business.is_active:
        return mc_mailboxes.LOGIN_DISALLOWED
    return mc_mailboxes.ACTIVE


# --------------------------------------------------------------------------- #
# Mailboxes
# --------------------------------------------------------------------------- #
def create_mailbox(
    *,
    business: Business,
    domain: Domain,
    local_part: str,
    display_name: str = "",
    quota_mb: int | None = None,
    actor=None,
    request=None,
) -> tuple[Mailbox, str]:
    """Returns (mailbox, temporary_password). The password is shown once and never stored."""
    local = normalize_local_part(local_part)
    address = f"{local}@{domain.name}"
    password = generate_password()
    remote_created = False
    client = get_client()

    try:
        with transaction.atomic():
            business = _lock_business(business)
            _require_mail_domain(domain, business)
            plan = business.plan
            if business.mailboxes.exclude(status=Mailbox.Status.DELETING).count() >= plan.max_mailboxes:
                raise QuotaExceeded(f"Your plan allows at most {plan.max_mailboxes} mailboxes.")
            quota = quota_mb if quota_mb is not None else min(plan.default_mailbox_quota_mb, plan.max_mailbox_quota_mb)
            _validate_quota(business, quota)
            if _address_taken(address):
                raise Conflict(f"{address} is already in use.")

            mailbox = Mailbox.objects.create(
                business=business,
                domain=domain,
                local_part=local,
                email=address,
                display_name=(display_name or "").strip()[:200],
                quota_mb=quota,
                status=Mailbox.Status.PENDING,
            )
            try:
                mc_mailboxes.create_mailbox(
                    local_part=local,
                    domain=domain.name,
                    name=mailbox.display_name or local,
                    quota_mb=quota,
                    password=password,
                    force_password_change=True,
                    client=client,
                )
                remote_created = True
                mc_mailboxes.set_rate_limit(address, mailbox.effective_hourly_limit(), client)
            except MailcowError as exc:
                raise_conflict_or_reraise(exc, f"{address} already exists on the mail server.")

            mailbox.status = Mailbox.Status.ACTIVE
            mailbox.mailcow_id = address
            mailbox.save(update_fields=["status", "mailcow_id", "updated_at"])
            audit.record(
                "mailbox.created",
                actor=actor,
                request=request,
                business=business,
                obj=mailbox,
                metadata={"quota_mb": quota},
            )
    except Exception:
        if remote_created:
            _compensate_mailbox_create(address)
        raise
    return mailbox, password


def _compensate_mailbox_create(address: str) -> None:
    try:
        mc_mailboxes.delete_mailbox(address)
        logger.warning("Rolled back Mailcow mailbox %s after local failure", address)
    except MailcowError as exc:
        logger.error("Compensation failed for %s: %s", address, exc.message)
        raise_alert(
            f"orphan-mailbox:{address}",
            f"Orphaned mailbox on Mailcow: {address}",
            f"{address} was created on Mailcow but the platform could not record it, and automatic "
            f"rollback failed ({exc.message}). The next sync will import it; review it manually.",
            severity="CRITICAL",
        )


def update_mailbox(
    mailbox: Mailbox,
    *,
    actor,
    request=None,
    display_name=None,
    quota_mb=None,
    outbound_limit_per_hour=None,
    outbound_limit_per_day=None,
    limits_supplied=False,
) -> Mailbox:
    attrs, changes = {}, {}
    with transaction.atomic():
        business = _lock_business(mailbox.business)
        mailbox = Mailbox.objects.select_for_update().get(pk=mailbox.pk)
        if mailbox.status in (Mailbox.Status.PENDING, Mailbox.Status.DELETING, Mailbox.Status.FAILED):
            raise ServiceError("This mailbox cannot be edited in its current state.")
        if display_name is not None and display_name.strip() != mailbox.display_name:
            mailbox.display_name = display_name.strip()[:200]
            attrs["name"] = mailbox.display_name or mailbox.local_part
            changes["display_name"] = mailbox.display_name
        if quota_mb is not None and quota_mb != mailbox.quota_mb:
            _validate_quota(business, quota_mb, exclude_mailbox_id=mailbox.pk)
            if quota_mb * 1024 * 1024 < mailbox.used_bytes:
                raise ServiceError("New quota is smaller than the storage already used.")
            mailbox.quota_mb = quota_mb
            attrs["quota"] = str(quota_mb)
            changes["quota_mb"] = quota_mb
        rate_changed = False
        if limits_supplied:
            if outbound_limit_per_hour != mailbox.outbound_limit_per_hour:
                mailbox.outbound_limit_per_hour = outbound_limit_per_hour
                rate_changed = True
                changes["outbound_limit_per_hour"] = outbound_limit_per_hour
            if outbound_limit_per_day != mailbox.outbound_limit_per_day:
                mailbox.outbound_limit_per_day = outbound_limit_per_day
                changes["outbound_limit_per_day"] = outbound_limit_per_day
        if not changes:
            return mailbox
        client = get_client()
        if attrs:
            mc_mailboxes.edit_mailbox(mailbox.email, attrs, client)
        if rate_changed:
            mc_mailboxes.set_rate_limit(mailbox.email, mailbox.effective_hourly_limit(), client)
        mailbox.save()
        audit.record("mailbox.updated", actor=actor, request=request, business=business, obj=mailbox, metadata=changes)
    return mailbox


def set_mailbox_status(mailbox: Mailbox, status: str, *, actor, request=None, reason: str = "") -> Mailbox:
    allowed = {Mailbox.Status.ACTIVE, Mailbox.Status.SUSPENDED, Mailbox.Status.DISABLED}
    if status not in allowed:
        raise ServiceError("Invalid status.")
    with transaction.atomic():
        mailbox = Mailbox.objects.select_for_update().select_related("business").get(pk=mailbox.pk)
        if mailbox.status not in allowed:
            raise ServiceError("This mailbox cannot change status in its current state.")
        if mailbox.status == status:
            return mailbox
        previous = mailbox.status
        mailbox.status = status
        mc_mailboxes.set_active_state(mailbox.email, desired_remote_state(mailbox))
        mailbox.save(update_fields=["status", "updated_at"])
        action = {
            Mailbox.Status.ACTIVE: "mailbox.activated",
            Mailbox.Status.SUSPENDED: "mailbox.suspended",
            Mailbox.Status.DISABLED: "mailbox.disabled",
        }[status]
        audit.record(
            action,
            actor=actor,
            request=request,
            business=mailbox.business,
            obj=mailbox,
            metadata={"previous": previous, "reason": reason},
        )
    return mailbox


def suspend_outbound(mailbox: Mailbox, *, reason: str, actor=None, request=None) -> Mailbox:
    """Block authenticated SMTP for one mailbox. Incoming mail keeps flowing."""
    with transaction.atomic():
        mailbox = Mailbox.objects.select_for_update().select_related("business").get(pk=mailbox.pk)
        if mailbox.outbound_suspended:
            return mailbox
        mc_mailboxes.set_smtp_access(mailbox.email, False)
        mailbox.outbound_suspended = True
        mailbox.outbound_suspended_reason = reason[:255]
        mailbox.outbound_suspended_at = timezone.now()
        mailbox.save(
            update_fields=["outbound_suspended", "outbound_suspended_reason", "outbound_suspended_at", "updated_at"]
        )
        audit.record(
            "mailbox.outbound_suspended",
            actor=actor,
            request=request,
            business=mailbox.business,
            obj=mailbox,
            metadata={"reason": reason},
        )
    return mailbox


def restore_outbound(mailbox: Mailbox, *, actor, request=None, note: str = "") -> Mailbox:
    with transaction.atomic():
        mailbox = Mailbox.objects.select_for_update().select_related("business").get(pk=mailbox.pk)
        if not mailbox.outbound_suspended:
            return mailbox
        mc_mailboxes.set_smtp_access(mailbox.email, True)
        mailbox.outbound_suspended = False
        mailbox.outbound_suspended_reason = ""
        mailbox.outbound_suspended_at = None
        mailbox.save(
            update_fields=["outbound_suspended", "outbound_suspended_reason", "outbound_suspended_at", "updated_at"]
        )
        audit.record(
            "mailbox.outbound_restored",
            actor=actor,
            request=request,
            business=mailbox.business,
            obj=mailbox,
            metadata={"note": note},
        )
    return mailbox


def reset_password(mailbox: Mailbox, *, actor, request=None) -> str:
    if mailbox.status not in (Mailbox.Status.ACTIVE, Mailbox.Status.SUSPENDED, Mailbox.Status.DISABLED):
        raise ServiceError("This mailbox cannot be modified in its current state.")
    password = generate_password()
    mc_mailboxes.set_password(mailbox.email, password, force_change=True)
    audit.record("mailbox.password_reset", actor=actor, request=request, business=mailbox.business, obj=mailbox)
    return password


def delete_mailbox(mailbox: Mailbox, *, actor, request=None) -> None:
    with transaction.atomic():
        locked = Mailbox.objects.select_for_update().get(pk=mailbox.pk)
        if locked.status == Mailbox.Status.DELETING:
            raise Conflict("Mailbox is already being deleted.")
        previous = locked.status
        locked.status = Mailbox.Status.DELETING
        locked.save(update_fields=["status", "updated_at"])
    try:
        mc_mailboxes.delete_mailbox(mailbox.email)
    except MailcowError:
        Mailbox.objects.filter(pk=mailbox.pk).update(status=previous)
        raise
    business, email = mailbox.business, mailbox.email
    Mailbox.objects.filter(pk=mailbox.pk).delete()
    audit.record("mailbox.deleted", actor=actor, request=request, business=business, metadata={"email": email})


# --------------------------------------------------------------------------- #
# Aliases
# --------------------------------------------------------------------------- #
def normalize_destinations(destinations) -> list[str]:
    if isinstance(destinations, str):
        destinations = destinations.replace("\n", ",").split(",")
    cleaned = []
    for item in destinations or []:
        addr = str(item).strip().lower()
        if not addr:
            continue
        try:
            validate_email(addr)
        except ValidationError as exc:
            raise ServiceError(f"'{addr}' is not a valid e-mail address.") from exc
        if addr not in cleaned:
            cleaned.append(addr)
    if not cleaned:
        raise ServiceError("At least one destination address is required.")
    if len(cleaned) > MAX_ALIAS_DESTINATIONS:
        raise ServiceError(f"An alias may have at most {MAX_ALIAS_DESTINATIONS} destinations.")
    return cleaned


def create_alias(
    *, business: Business, domain: Domain, local_part: str, destinations, actor=None, request=None
) -> Alias:
    local = normalize_local_part(local_part, allow_reserved=True)
    address = f"{local}@{domain.name}"
    dests = normalize_destinations(destinations)
    if address in dests:
        raise ServiceError("An alias cannot forward to itself.")
    remote_id = None
    try:
        with transaction.atomic():
            business = _lock_business(business)
            _require_mail_domain(domain, business)
            if business.aliases.count() >= business.plan.max_aliases:
                raise QuotaExceeded(f"Your plan allows at most {business.plan.max_aliases} aliases.")
            if _address_taken(address):
                raise Conflict(f"{address} is already in use.")
            alias = Alias.objects.create(business=business, domain=domain, source_address=address, destinations=dests)
            try:
                remote_id = mc_aliases.create_alias(address, dests)
            except MailcowError as exc:
                raise_conflict_or_reraise(exc, f"{address} already exists on the mail server.")
            alias.mailcow_id = remote_id
            alias.save(update_fields=["mailcow_id", "updated_at"])
            audit.record(
                "alias.created",
                actor=actor,
                request=request,
                business=business,
                obj=alias,
                metadata={"destinations": dests},
            )
    except Exception:
        if remote_id:
            try:
                mc_aliases.delete_alias(remote_id)
            except MailcowError:
                logger.exception("Failed to roll back alias %s", address)
        raise
    return alias


def update_alias(alias: Alias, *, actor, request=None, destinations=None, status=None) -> Alias:
    with transaction.atomic():
        alias = Alias.objects.select_for_update().select_related("business").get(pk=alias.pk)
        if destinations is not None:
            dests = normalize_destinations(destinations)
            if alias.source_address in dests:
                raise ServiceError("An alias cannot forward to itself.")
            alias.destinations = dests
        if status is not None:
            if status not in Alias.Status.values:
                raise ServiceError("Invalid status.")
            alias.status = status
        mc_aliases.update_alias(alias.mailcow_id, alias.destinations, active=alias.status == Alias.Status.ACTIVE)
        alias.save()
        audit.record(
            "alias.updated",
            actor=actor,
            request=request,
            business=alias.business,
            obj=alias,
            metadata={"destinations": alias.destinations, "status": alias.status},
        )
    return alias


def delete_alias(alias: Alias, *, actor, request=None) -> None:
    mc_aliases.delete_alias(alias.mailcow_id)
    business, address = alias.business, alias.source_address
    alias.delete()
    audit.record("alias.deleted", actor=actor, request=request, business=business, metadata={"address": address})
