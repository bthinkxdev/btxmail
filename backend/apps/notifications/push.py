"""
Web Push delivery.

Everything user-visible goes through `notify_users()`: it picks the subscriptions of the users
who have the category enabled and queues one Celery task per device. Payloads are encrypted
end to end by the Web Push protocol; the platform never stores message content.
"""

from __future__ import annotations

import logging
import re
from email.header import decode_header, make_header
from email.utils import parseaddr
from urllib.parse import urlparse

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.accounts.models import PLATFORM_ROLES, Role, User

from .models import MailWatch, PushSubscription

logger = logging.getLogger(__name__)

CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]+")
PREFERENCE_FIELDS = {"new_mail", "security", "domains", "system"}


def push_enabled() -> bool:
    return bool(settings.VAPID_PUBLIC_KEY and settings.VAPID_PRIVATE_KEY)


def endpoint_allowed(url: str) -> bool:
    """Only genuine browser push services are accepted (prevents server-side request forgery)."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.port not in (None, 443):
        return False
    host = parsed.hostname.lower()
    return any(
        host == s.lstrip(".") or host.endswith("." + s.lstrip("."))
        for s in settings.PUSH_ENDPOINT_ALLOWED_SUFFIXES
    )


def clean(text: str, limit: int) -> str:
    text = CONTROL_CHARS.sub(" ", str(text or "")).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def decode_mime(value: str) -> str:
    """Decode RFC 2047 encoded words (=?utf-8?B?...?=) as found in raw From/Subject headers."""
    try:
        return str(make_header(decode_header(value or "")))
    except Exception:  # noqa: BLE001 - malformed headers must never break delivery
        return value or ""


def notify_users(
    users,
    *,
    kind: str,
    preference: str,
    title: str,
    body: str,
    url: str = "/",
    tag: str = "",
    center: str = "",
    account: str = "",
    urgency: str = "normal",
    extra: dict | None = None,
) -> int:
    """Queue a push to every device of `users` that has `preference` enabled. Returns devices targeted."""
    from .tasks import send_push

    if not push_enabled():
        return 0
    assert preference in PREFERENCE_FIELDS
    subs = list(
        PushSubscription.objects.filter(user__in=users, user__is_active=True, active=True)
        .exclude(**{f"user__push_preference__{preference}": False})
        .values_list("pk", flat=True)
    )
    payload = {
        "kind": kind,
        "title": clean(title, 100),
        "body": clean(body, 200),
        "tag": tag or kind,
        "url": url,
        "center": clean(center, 80),
        "account": clean(account, 120),
        "ts": int(timezone.now().timestamp() * 1000),
        **(extra or {}),
    }
    for pk in subs:
        transaction.on_commit(lambda pk=pk: send_push.delay(pk, payload, urgency))
    return len(subs)


# --------------------------------------------------------------------------- #
# Recipients
# --------------------------------------------------------------------------- #
def staff_users():
    return User.objects.filter(role__in=PLATFORM_ROLES, is_active=True)


def business_admins(business):
    if business is None:
        return User.objects.none()
    return User.objects.filter(role=Role.BUSINESS_ADMIN, business=business, is_active=True)


def staff_and_admins(business):
    return User.objects.filter(Q(pk__in=staff_users()) | Q(pk__in=business_admins(business))).distinct()


def mail_watchers(mailbox):
    """Users who asked to watch the mailbox, plus the portal user who owns the address."""
    scoped = Q(business=mailbox.business_id) | Q(role__in=PLATFORM_ROLES)
    return (
        User.objects.filter(is_active=True)
        .filter(scoped)
        .filter(Q(pk__in=MailWatch.objects.filter(mailbox=mailbox).values("user")) | Q(email__iexact=mailbox.email))
    )


# --------------------------------------------------------------------------- #
# Events
# --------------------------------------------------------------------------- #
def notify_new_mail(recipient: str, sender: str, subject: str) -> int:
    from apps.mailboxes.models import Mailbox

    mailbox = Mailbox.objects.select_related("business").filter(email__iexact=(recipient or "").strip()).first()
    if mailbox is None or mailbox.status not in (Mailbox.Status.ACTIVE, Mailbox.Status.SUSPENDED):
        return 0
    minute = int(timezone.now().timestamp() // 60)
    key = f"push:mail:{mailbox.pk}:{minute}"
    cache.add(key, 0, 120)
    if cache.incr(key) > settings.PUSH_MAIL_RATE_PER_MINUTE:
        return 0  # flood protection; the device already shows a grouped notification

    name, address = parseaddr(decode_mime(sender))
    subject = decode_mime(subject)
    return notify_users(
        mail_watchers(mailbox),
        kind="mail",
        preference="new_mail",
        title=clean(name or address or "New message", 80),
        body=clean(subject, 140) or "(no subject)",
        url=settings.WEBMAIL_URL or "/",
        tag=f"mail:{mailbox.pk}",
        center=mailbox.business.name,
        account=mailbox.email,
        urgency="high",
        extra={"sender": clean(name or address, 80)},
    )


def notify_alert(alert) -> int:
    customer_facing = alert.key.startswith(("dns-failure", "domain-"))
    users = staff_and_admins(alert.business) if customer_facing and alert.business_id else staff_users()
    return notify_users(
        users,
        kind="alert",
        preference="domains" if customer_facing else "system",
        title=alert.title,
        body=alert.message.splitlines()[0] if alert.message else "",
        url="/domains" if customer_facing else "/system",
        tag=f"alert:{alert.key}",
        center=alert.business.name if alert.business_id else "",
        urgency="high" if alert.severity == "CRITICAL" else "normal",
    )


def notify_security_event(event) -> int:
    return notify_users(
        staff_and_admins(event.business),
        kind="security",
        preference="security",
        title=f"Security: {event.get_event_type_display()}",
        body=event.description or event.subject,
        url="/security",
        tag=f"security:{event.pk}",
        center=event.business.name if event.business_id else "",
        account=event.subject,
        urgency="high" if event.severity in ("HIGH", "CRITICAL") else "normal",
    )


def notify_domain_active(domain) -> int:
    return notify_users(
        business_admins(domain.business),
        kind="domain",
        preference="domains",
        title="Domain is ready",
        body=f"{domain.name} is verified and its DNS is correct. You can create mailboxes.",
        url=f"/domains/{domain.pk}",
        tag=f"domain:{domain.pk}",
        center=domain.business.name,
        account=domain.name,
    )
