"""Celery jobs: sync, abuse detection, monitoring, alerts."""

import time

import pytest
from django.core import mail

from apps.mailboxes import tasks as mailbox_tasks
from apps.mailboxes.models import Mailbox
from apps.monitoring import services as monitoring
from apps.monitoring.models import BlacklistCheck, HealthCheck
from apps.notifications.models import Alert
from apps.security import services as security
from apps.security.models import SecurityEvent

pytestmark = pytest.mark.django_db


@pytest.fixture
def mailbox(biz_client, domain):
    resp = biz_client.post("/api/mailboxes/", {"domain": domain.pk, "local_part": "sales"}, format="json")
    return Mailbox.objects.get(pk=resp.json()["id"])


# ----------------------------------------------------------------------------- sync
def test_sync_updates_usage_and_fixes_drift(mailbox, mailcow):
    remote = mailcow.mailboxes[mailbox.email]
    remote.update({"quota_used": 5 * 1024 * 1024, "messages": 42, "last_imap_login": str(int(time.time()))})
    remote["active"], remote["active_int"] = "0", 0  # someone disabled it directly in Mailcow
    remote["attributes"]["smtp_access"] = "0"

    stats = mailbox_tasks.sync_mailcow()
    assert stats["drift_fixed"] == 1
    mailbox.refresh_from_db()
    assert mailbox.used_bytes == 5 * 1024 * 1024
    assert mailbox.message_count == 42
    assert mailbox.last_login_at is not None
    assert remote["active"] == "1"
    assert remote["attributes"]["smtp_access"] == "1"


def test_sync_flags_missing_mailbox(mailbox, mailcow):
    del mailcow.mailboxes[mailbox.email]
    mailbox_tasks.sync_mailcow()
    mailbox.refresh_from_db()
    assert mailbox.status == "FAILED"
    assert Alert.objects.filter(key=f"mailbox-missing:{mailbox.email}").exists()


def test_sync_imports_external_mailbox_after_grace(domain, mailcow, monkeypatch):
    mailcow.mailboxes["rogue@abctraders.com"] = {
        "username": "rogue@abctraders.com",
        "domain": "abctraders.com",
        "name": "Rogue",
        "active": "1",
        "quota": 100 * 1024 * 1024,
        "quota_used": 0,
        "messages": 0,
        "attributes": {"smtp_access": "1"},
    }
    mailbox_tasks.sync_mailcow()
    assert not Mailbox.objects.filter(email="rogue@abctraders.com").exists()  # grace period
    monkeypatch.setattr(mailbox_tasks, "IMPORT_GRACE_SECONDS", 0)
    mailbox_tasks.sync_mailcow()
    imported = Mailbox.objects.get(email="rogue@abctraders.com")
    assert imported.business_id == domain.business_id and imported.quota_mb == 100


def test_business_suspension_blocks_logins(staff_client, business, mailbox, mailcow):
    staff_client.post(f"/api/businesses/{business.pk}/suspend/", {"reason": "Unpaid"}, format="json")
    assert mailcow.mailboxes[mailbox.email]["active"] == "2"
    staff_client.post(f"/api/businesses/{business.pk}/activate/")
    assert mailcow.mailboxes[mailbox.email]["active"] == "1"


def test_plan_change_pushes_limits(staff_client, business, mailbox, mailcow):
    from apps.businesses.models import Plan

    bigger = Plan.objects.create(
        code="big",
        name="Big",
        max_domains=5,
        max_mailboxes=50,
        max_aliases=100,
        default_mailbox_quota_mb=2048,
        max_mailbox_quota_mb=10240,
        total_storage_mb=100000,
        outbound_per_hour=77,
        outbound_per_day=500,
    )
    resp = staff_client.patch(f"/api/businesses/{business.pk}/", {"plan": bigger.pk}, format="json")
    assert resp.status_code == 200
    assert mailcow.domains["abctraders.com"]["mailboxes"] == "50"
    assert mailcow.rate_limits[mailbox.email]["rl_value"] == "77"


def test_plan_downgrade_blocked_when_over_limit(staff_client, business, mailbox):
    from apps.businesses.models import Plan

    tiny = Plan.objects.create(
        code="tiny",
        name="Tiny",
        max_domains=1,
        max_mailboxes=1,
        max_aliases=1,
        default_mailbox_quota_mb=10,
        max_mailbox_quota_mb=10,
        total_storage_mb=10,
    )
    resp = staff_client.patch(f"/api/businesses/{business.pk}/", {"plan": tiny.pk}, format="json")
    assert resp.status_code == 400


# ----------------------------------------------------------------------------- abuse
def test_high_outbound_volume_suspends_outbound_only(mailbox, mailcow):
    mailcow.add_outbound(mailbox.email, 500)  # hourly limit 20 × multiplier 3 = 60
    summary = security.detect_abuse()
    assert summary["events"] >= 1
    mailbox.refresh_from_db()
    assert mailbox.outbound_suspended
    assert mailbox.status == "ACTIVE"  # incoming mail continues
    assert mailcow.mailboxes[mailbox.email]["attributes"]["smtp_access"] == "0"
    event = SecurityEvent.objects.get(event_type="HIGH_OUTBOUND_VOLUME")
    assert event.action_taken == "OUTBOUND_SUSPENDED" and event.message_count == 500
    assert Alert.objects.filter(key__startswith="security:HIGH_OUTBOUND_VOLUME").exists()
    assert len(mail.outbox) >= 1  # alert e-mail delivered

    # Second run in the same hour does not duplicate the event
    security.detect_abuse()
    assert SecurityEvent.objects.filter(event_type="HIGH_OUTBOUND_VOLUME").count() == 1


def test_normal_volume_is_ignored(mailbox, mailcow):
    mailcow.add_outbound(mailbox.email, 10)
    security.detect_abuse()
    assert not SecurityEvent.objects.exists()


def test_daily_limit_enforced(mailbox, mailcow):
    mailcow.add_outbound(mailbox.email, 101, age_seconds=5 * 3600)  # outside the hour, inside the day
    security.detect_abuse()
    mailbox.refresh_from_db()
    assert mailbox.outbound_suspended


def test_outbound_spam_detection(mailbox, mailcow):
    mailcow.add_outbound(mailbox.email, 12, action="reject")
    security.detect_abuse()
    assert SecurityEvent.objects.filter(event_type="SPAM_ACTIVITY").exists()


def test_auth_failures_detected(mailbox, mailcow, settings):
    now = int(time.time())
    mailcow.logs["dovecot"] = [
        {
            "time": now,
            "message": f"imap-login: Disconnected (auth failed, 1 attempts in 2 secs): "
            f"user=<{mailbox.email}>, method=PLAIN, rip=192.0.2.{i % 2}, lip=10.0.0.1",
        }
        for i in range(settings.ABUSE_AUTH_FAILURE_THRESHOLD)
    ]
    security.detect_abuse()
    event = SecurityEvent.objects.get(event_type="LOGIN_BRUTE_FORCE")
    assert event.source_ip in ("192.0.2.0", "192.0.2.1")
    mailbox.refresh_from_db()
    assert not mailbox.outbound_suspended


def test_abuse_task_alerts_when_logs_unreachable(mailbox, mailcow):
    from apps.security.tasks import detect_abuse

    mailcow.fail("GET", "get/logs/rspamd-history", 500, times=5)
    assert "error" in detect_abuse()
    assert Alert.objects.filter(key="abuse-detection-unavailable").exists()


def test_staff_resolves_event(staff_client, biz_client, mailbox):
    event = security.record_event(event_type="SPAM_ACTIVITY", severity="HIGH", mailbox=mailbox)
    assert biz_client.post(f"/api/security-events/{event.pk}/resolve/").status_code == 403
    assert biz_client.get("/api/security-events/").json()["count"] == 1
    resp = staff_client.post(f"/api/security-events/{event.pk}/resolve/", {"note": "Password rotated"}, format="json")
    assert resp.json()["is_open"] is False


# ----------------------------------------------------------------------------- monitoring
def test_health_detects_down_containers_disk_and_queue(mailcow, monkeypatch, settings):
    monkeypatch.setattr(monitoring, "check_tls_certificate", lambda *a, **k: "OK")
    mailcow.containers["postfix-mailcow"]["state"] = "exited"
    mailcow.vmail["used_percent"] = "91%"
    mailcow.queue = [{"queue_id": str(i)} for i in range(settings.MAIL_QUEUE_ALERT)]
    result = monitoring.check_mailcow_health()
    assert result["containers"] == "CRITICAL"
    keys = set(Alert.objects.values_list("key", flat=True))
    assert {"containers-down:postfix-mailcow", "disk-usage", "mail-queue"} <= keys


def test_health_when_api_down(mailcow):
    mailcow.fail("GET", "get/status/containers", 503, times=5)
    assert monitoring.check_mailcow_health() == {"mailcow_api": "CRITICAL"}
    assert Alert.objects.filter(key="mail-server-down").exists()


def test_blacklist_check(fake_dns, settings):
    settings.DNSBL_ZONES = ["zen.spamhaus.org", "bl.spamcop.net", "bad.example"]
    fake_dns.set_a("10.113.0.203.zen.spamhaus.org", "127.0.0.2")
    fake_dns.set_a("10.113.0.203.bad.example", "127.255.255.254")  # resolver refused
    result = monitoring.check_blacklists()
    assert result["listed"] == ["zen.spamhaus.org"]
    assert BlacklistCheck.objects.get(zone="bad.example").error
    assert Alert.objects.filter(key__startswith="blacklist:").exists()


def test_backup_report_endpoint(client, db):
    url = "/api/monitoring/backup-report/"
    assert client.post(url, {"status": "success"}, content_type="application/json").status_code == 401
    resp = client.post(
        url,
        {"status": "success", "message": "nightly"},
        content_type="application/json",
        HTTP_AUTHORIZATION="Bearer backup-token-123",
    )
    assert resp.status_code == 200
    assert monitoring.check_backup_freshness() == "ok"
    client.post(
        url,
        {"status": "failure", "message": "disk full"},
        content_type="application/json",
        HTTP_AUTHORIZATION="Bearer backup-token-123",
    )
    assert Alert.objects.filter(key="backup-failed").exists()


def test_stale_backup_alerts(db):
    assert monitoring.check_backup_freshness() == "stale"
    assert Alert.objects.filter(key="backup-stale").exists()


def test_alert_deduplication(db):
    from apps.notifications.service import raise_alert

    raise_alert("k1", "t", "m")
    raise_alert("k1", "t", "m")
    assert Alert.objects.filter(key="k1").count() == 1


def test_reputation_endpoint(staff_client, mailcow, monkeypatch):
    monkeypatch.setattr(monitoring, "check_tls_certificate", lambda *a, **k: "OK")
    monitoring.check_mailcow_health()
    body = staff_client.get("/api/monitoring/reputation/").json()
    assert body["status"] == "HEALTHY"
    assert body["components"]["containers"]["status"] == "OK"
    assert HealthCheck.objects.exists()


def test_prune_task(db):
    from apps.monitoring.tasks import prune_old_records

    assert set(prune_old_records()) == {"health", "blacklist", "alerts", "audit"}
