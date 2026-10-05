from __future__ import annotations

import logging
import socket
import ssl
from datetime import UTC, datetime, timedelta

from django.conf import settings
from django.utils import timezone

from apps.domains import dns_checks
from apps.mailcow import health as mc_health
from apps.mailcow.client import get_client
from apps.mailcow.exceptions import MailcowError
from apps.notifications.service import raise_alert

from .models import BlacklistCheck, HealthCheck

logger = logging.getLogger(__name__)

S = HealthCheck.Status


def _record(component: str, status: str, message: str, details: dict | None = None) -> HealthCheck:
    return HealthCheck.objects.create(component=component, status=status, message=message[:500], details=details or {})


# --------------------------------------------------------------------------- #
def check_mailcow_health() -> dict:
    client = get_client()
    results = {}
    try:
        containers = mc_health.container_status(client)
    except MailcowError as exc:
        _record("mailcow_api", S.CRITICAL, exc.message)
        raise_alert(
            "mail-server-down",
            "Mail server API unreachable",
            f"Mailcow API check failed: {exc.message}",
            severity="CRITICAL",
        )
        return {"mailcow_api": S.CRITICAL}
    _record("mailcow_api", S.OK, "Mailcow API reachable.")
    results["mailcow_api"] = S.OK

    down = sorted(
        name for name in mc_health.CRITICAL_CONTAINERS if containers and containers.get(name, "missing") != "running"
    )
    if down:
        _record("containers", S.CRITICAL, f"Not running: {', '.join(down)}", {"containers": containers})
        raise_alert(
            f"containers-down:{','.join(down)}",
            "Mail server component failure",
            f"These Mailcow containers are not running: {', '.join(down)}",
            severity="CRITICAL",
        )
        results["containers"] = S.CRITICAL
    else:
        _record("containers", S.OK, f"{len(containers)} containers running.", {"containers": containers})
        results["containers"] = S.OK

    try:
        usage = mc_health.vmail_usage(client)
        pct = usage.get("used_percent")
        if pct is None:
            _record("vmail_disk", S.UNKNOWN, "Disk usage not reported.", usage)
        elif pct >= settings.DISK_ALERT_PERCENT:
            _record("vmail_disk", S.CRITICAL if pct >= 90 else S.WARN, f"Mail storage {pct:.0f}% used.", usage)
            raise_alert(
                "disk-usage",
                f"Mail storage {pct:.0f}% full",
                f"vmail volume usage is {pct:.0f}% ({usage.get('used')} of {usage.get('total')}).",
                severity="CRITICAL" if pct >= 90 else "WARNING",
            )
        else:
            _record("vmail_disk", S.OK, f"Mail storage {pct:.0f}% used.", usage)
        results["vmail_disk"] = "checked"
    except MailcowError as exc:
        _record("vmail_disk", S.UNKNOWN, exc.message)

    try:
        queued = mc_health.queue_size(client)
        if queued >= settings.MAIL_QUEUE_ALERT:
            _record("mail_queue", S.WARN, f"{queued} messages queued.", {"queued": queued})
            raise_alert("mail-queue", "SMTP queue abnormal", f"{queued} messages are waiting in the Postfix queue.")
        else:
            _record("mail_queue", S.OK, f"{queued} messages queued.", {"queued": queued})
        results["mail_queue"] = queued
    except MailcowError as exc:
        _record("mail_queue", S.UNKNOWN, exc.message)

    results["tls_certificate"] = check_tls_certificate()
    return results


def check_tls_certificate(host: str | None = None, port: int = 443) -> str:
    host = host or settings.MAIL_HOSTNAME
    try:
        context = ssl.create_default_context()
        with socket.create_connection((host, port), timeout=10) as sock:
            with context.wrap_socket(sock, server_hostname=host) as tls:
                cert = tls.getpeercert()
        expires = datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z").replace(tzinfo=UTC)
    except (OSError, ssl.SSLError, KeyError, ValueError) as exc:
        _record("tls_certificate", S.CRITICAL, f"TLS check failed for {host}: {exc}")
        raise_alert(
            f"tls:{host}", f"TLS problem on {host}", f"Could not validate the certificate: {exc}", severity="CRITICAL"
        )
        return S.CRITICAL
    days = (expires - timezone.now()).days
    if days < settings.TLS_EXPIRY_ALERT_DAYS:
        _record(
            "tls_certificate",
            S.WARN if days > 3 else S.CRITICAL,
            f"Certificate expires in {days} days.",
            {"expires": expires.isoformat()},
        )
        raise_alert(
            f"tls-expiry:{host}",
            f"Certificate for {host} expires in {days} days",
            f"Renewal may be failing. Expiry: {expires.isoformat()}",
            severity="CRITICAL" if days <= 3 else "WARNING",
        )
        return S.WARN
    _record("tls_certificate", S.OK, f"Certificate valid for {days} more days.", {"expires": expires.isoformat()})
    return S.OK


# --------------------------------------------------------------------------- #
def check_blacklists() -> dict:
    ip = settings.MAIL_IPV4
    if not ip:
        return {"skipped": "MAIL_IPV4 not configured"}
    listed = []
    for zone in settings.DNSBL_ZONES:
        try:
            is_listed, response = dns_checks.dnsbl_lookup(ip, zone)
            BlacklistCheck.objects.create(ip_address=ip, zone=zone, listed=is_listed, response=response)
            if is_listed:
                listed.append(zone)
        except dns_checks.DNSLookupError as exc:
            BlacklistCheck.objects.create(ip_address=ip, zone=zone, listed=False, error=str(exc)[:255])
    if listed:
        raise_alert(
            f"blacklist:{','.join(sorted(listed))}",
            f"Mail IP {ip} is blacklisted",
            f"{ip} is listed on: {', '.join(listed)}. Investigate outbound abuse and request delisting.",
            severity="CRITICAL",
        )
    return {"ip": ip, "listed": listed}


# --------------------------------------------------------------------------- #
def record_backup_report(*, status: str, message: str = "", details: dict | None = None) -> HealthCheck:
    level = S.OK if status == "success" else S.CRITICAL
    check = _record("backup", level, message or f"Backup {status}.", details)
    if level != S.OK:
        raise_alert(
            "backup-failed", "Mail backup failed", message or "The backup job reported a failure.", severity="CRITICAL"
        )
    return check


def check_backup_freshness() -> str:
    last_ok = HealthCheck.objects.filter(component="backup", status=S.OK).order_by("-checked_at").first()
    limit = timezone.now() - timedelta(hours=settings.BACKUP_MAX_AGE_HOURS)
    if last_ok is None or last_ok.checked_at < limit:
        when = last_ok.checked_at.isoformat() if last_ok else "never"
        raise_alert(
            "backup-stale",
            "No recent successful backup",
            f"Last successful backup report: {when}. Expected within {settings.BACKUP_MAX_AGE_HOURS}h.",
            severity="CRITICAL",
        )
        return "stale"
    return "ok"


def reputation_summary() -> dict:
    latest = {}
    for check in BlacklistCheck.objects.order_by("-checked_at")[: max(len(settings.DNSBL_ZONES) * 3, 10)]:
        latest.setdefault(check.zone, check)
    components = {}
    for name in ("mailcow_api", "containers", "vmail_disk", "mail_queue", "tls_certificate", "backup"):
        hc = HealthCheck.objects.filter(component=name).order_by("-checked_at").first()
        if hc:
            components[name] = {
                "status": hc.status,
                "message": hc.message,
                "checked_at": hc.checked_at,
                "details": hc.details,
            }
    listed = [z for z, c in latest.items() if c.listed]
    return {
        "mail_ip": settings.MAIL_IPV4,
        "mail_hostname": settings.MAIL_HOSTNAME,
        "status": "LISTED" if listed else "HEALTHY",
        "blacklists": [
            {"zone": z, "listed": c.listed, "response": c.response, "error": c.error, "checked_at": c.checked_at}
            for z, c in sorted(latest.items())
        ],
        "components": components,
    }
