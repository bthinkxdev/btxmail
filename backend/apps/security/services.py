"""
Abuse detection.

Signals come from Mailcow logs:
  * Rspamd history — every message with an authenticated `user` is an outbound
    submission by that mailbox; spam verdicts on outbound mail are a strong
    compromise signal.
  * Ratelimited log — Mailcow already enforces the per-mailbox hourly limit
    we configure; repeated hits mean the mailbox is trying to exceed it.
  * Dovecot log — authentication failures per mailbox.

Policy (README §14/§15):
  * outbound/hour > hourly limit × ABUSE_HOURLY_MULTIPLIER, or outbound/day >
    daily limit  → HIGH_OUTBOUND_VOLUME, outbound suspended automatically;
  * ≥ ABUSE_SPAM_THRESHOLD outbound spam verdicts/hour → SPAM_ACTIVITY, suspended;
  * rate-limit hits → RATE_LIMITED event (alert);
  * ≥ ABUSE_AUTH_FAILURE_THRESHOLD auth failures/hour → AUTH_FAILURE event.
Incoming mail is never stopped by these actions.
"""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from apps.audit import service as audit
from apps.mailboxes.models import Mailbox
from apps.mailcow import logs as mc_logs
from apps.mailcow.client import get_client
from apps.mailcow.exceptions import MailcowError
from apps.notifications.service import raise_alert

from .models import SecurityEvent

logger = logging.getLogger(__name__)

SPAM_ACTIONS = {"reject", "add header", "rewrite subject", "soft reject"}
RATE_LIMIT_SUSPEND_HITS = 50

ET = SecurityEvent.EventType
SEV = SecurityEvent.Severity


def record_event(
    *,
    event_type,
    severity,
    subject="",
    mailbox=None,
    business=None,
    source_ip=None,
    message_count=0,
    description="",
    details=None,
    fingerprint="",
    action=SecurityEvent.Action.NONE,
) -> SecurityEvent | None:
    if fingerprint and SecurityEvent.objects.filter(fingerprint=fingerprint).exists():
        return None
    if mailbox is not None and business is None:
        business = mailbox.business
    event = SecurityEvent.objects.create(
        event_type=event_type,
        severity=severity,
        subject=subject or (mailbox.email if mailbox else ""),
        mailbox=mailbox,
        business=business,
        source_ip=source_ip,
        message_count=message_count,
        description=description,
        details=details or {},
        fingerprint=fingerprint,
        action_taken=action,
    )
    from apps.notifications.push import notify_security_event

    notify_security_event(event)
    return event


def resolve_event(event: SecurityEvent, *, actor, request=None, note: str = "") -> SecurityEvent:
    if event.resolved_at:
        return event
    event.resolved_at = timezone.now()
    event.resolved_by = actor
    event.resolution_note = note[:2000]
    event.save(update_fields=["resolved_at", "resolved_by", "resolution_note"])
    audit.record(
        "security_event.resolved",
        actor=actor,
        request=request,
        business=event.business,
        obj=event,
        metadata={"note": note},
    )
    return event


def _suspend(mailbox: Mailbox, reason: str) -> bool:
    from apps.mailboxes.services import suspend_outbound

    if not settings.ABUSE_AUTO_SUSPEND or mailbox.outbound_suspended:
        return False
    try:
        suspend_outbound(mailbox, reason=reason)
        return True
    except MailcowError as exc:
        logger.error("Automatic outbound suspension of %s failed: %s", mailbox.email, exc.message)
        raise_alert(
            f"suspend-failed:{mailbox.email}",
            f"Could not suspend outbound mail for {mailbox.email}",
            f"Abuse detected ({reason}) but Mailcow refused the suspension: {exc.message}. Act manually.",
            severity="CRITICAL",
            business=mailbox.business,
        )
        return False


def _handle(mailbox: Mailbox, *, event_type, severity, count, description, details, suspend, ip=None) -> None:
    bucket = timezone.now().strftime("%Y%m%d%H")
    fingerprint = f"{event_type}:{mailbox.email}:{bucket}"
    if SecurityEvent.objects.filter(fingerprint=fingerprint).exists():
        return
    suspended = _suspend(mailbox, description) if suspend else False
    event = record_event(
        event_type=event_type,
        severity=severity,
        mailbox=mailbox,
        source_ip=ip,
        message_count=count,
        description=description,
        details=details,
        fingerprint=fingerprint,
        action=SecurityEvent.Action.OUTBOUND_SUSPENDED if suspended else SecurityEvent.Action.ALERTED,
    )
    if event is None:
        return
    action_text = "OUTBOUND SUSPENDED" if suspended else "Alert only"
    raise_alert(
        f"security:{fingerprint}",
        f"Security alert: {mailbox.email}",
        f"Mailbox: {mailbox.email}\nBusiness: {mailbox.business.name}\nReason: {description}\n"
        f"Count: {count}\nAction: {action_text}",
        severity="CRITICAL" if severity in (SEV.HIGH, SEV.CRITICAL) else "WARNING",
        business=mailbox.business,
    )


def detect_abuse() -> dict:
    client = get_client()
    now = timezone.now()
    hour_ago = now - timedelta(hours=1)
    day_ago = now - timedelta(days=1)
    lookback = settings.ABUSE_LOG_LOOKBACK

    sent_hour, sent_day, spam_hour = Counter(), Counter(), Counter()
    ips: dict[str, set] = defaultdict(set)
    for row in mc_logs.rspamd_history(lookback, client):
        user = row["user"]
        if not user:
            continue
        if row["time"] >= day_ago:
            sent_day[user] += 1
        if row["time"] >= hour_ago:
            sent_hour[user] += 1
            if row["action"] in SPAM_ACTIONS:
                spam_hour[user] += 1
            if row["ip"]:
                ips[user].add(str(row["ip"]))

    rl_hour = Counter(r["user"] for r in mc_logs.ratelimited(lookback, client) if r["time"] >= hour_ago)

    auth_fail = Counter()
    auth_ips: dict[str, Counter] = defaultdict(Counter)
    for r in mc_logs.auth_failures(lookback, client):
        if r["time"] >= hour_ago:
            auth_fail[r["user"]] += 1
            auth_ips[r["user"]][r["ip"]] += 1

    users = set(sent_hour) | set(sent_day) | set(rl_hour) | set(auth_fail)
    mailboxes = {
        m.email.lower(): m for m in Mailbox.objects.filter(email__in=list(users)).select_related("business__plan")
    }
    summary = {"checked": len(mailboxes), "events": 0}

    for email, mailbox in mailboxes.items():
        before = SecurityEvent.objects.count()
        hourly_limit = mailbox.effective_hourly_limit()
        daily_limit = mailbox.effective_daily_limit()
        hour_count, day_count = sent_hour[email], sent_day[email]
        common = {"source_ips": sorted(ips[email])[:20], "hourly_limit": hourly_limit, "daily_limit": daily_limit}

        if hour_count > hourly_limit * settings.ABUSE_HOURLY_MULTIPLIER or day_count > daily_limit:
            _handle(
                mailbox,
                event_type=ET.HIGH_OUTBOUND_VOLUME,
                severity=SEV.HIGH,
                count=max(hour_count, day_count),
                description=(
                    f"Abnormal outbound traffic: {hour_count} messages in the last hour, "
                    f"{day_count} in 24h (limits {hourly_limit}/h, {daily_limit}/day)."
                ),
                details={**common, "last_hour": hour_count, "last_day": day_count},
                suspend=True,
            )
        if spam_hour[email] >= settings.ABUSE_SPAM_THRESHOLD:
            _handle(
                mailbox,
                event_type=ET.SPAM_ACTIVITY,
                severity=SEV.CRITICAL,
                count=spam_hour[email],
                description=f"{spam_hour[email]} outbound messages flagged as spam in the last hour.",
                details=common,
                suspend=True,
            )
        if rl_hour[email]:
            hits = rl_hour[email]
            _handle(
                mailbox,
                event_type=ET.RATE_LIMITED,
                severity=SEV.HIGH if hits >= RATE_LIMIT_SUSPEND_HITS else SEV.MEDIUM,
                count=hits,
                description=f"Hit the outbound rate limit {hits} time(s) in the last hour.",
                details=common,
                suspend=hits >= RATE_LIMIT_SUSPEND_HITS,
            )
        if auth_fail[email] >= settings.ABUSE_AUTH_FAILURE_THRESHOLD:
            top_ip, _ = auth_ips[email].most_common(1)[0]
            distinct = len(auth_ips[email])
            _handle(
                mailbox,
                event_type=ET.LOGIN_BRUTE_FORCE if distinct <= 3 else ET.AUTH_FAILURE,
                severity=SEV.HIGH,
                count=auth_fail[email],
                description=f"{auth_fail[email]} failed logins in the last hour from {distinct} IP(s).",
                details={"ips": dict(auth_ips[email].most_common(20))},
                suspend=False,
                ip=top_ip,
            )
        summary["events"] += SecurityEvent.objects.count() - before
    return summary
