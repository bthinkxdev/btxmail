import json

import pytest
from pywebpush import WebPushException

from apps.accounts.models import Role
from apps.mailboxes.models import Mailbox
from apps.notifications.models import MailWatch, PushSubscription

from .conftest import client_for, make_user

ENDPOINT = "https://fcm.googleapis.com/fcm/send/abc123"
KEYS = {"p256dh": "BNc" + "x" * 80, "auth": "authsecret123"}
HOOK_TOKEN = "h" * 40


@pytest.fixture(autouse=True)
def push_settings(settings):
    settings.VAPID_PUBLIC_KEY = (
        "BLNssA8rX6XZowMwwrcn5-iGQT0GR_T_fnCmyVV748AUOdSDwOnkwkpNk-peGJj3AFIA7TFNfd-3wN6jLOMpqI4"
    )
    settings.VAPID_PRIVATE_KEY = "MPoh9nawGCA-YX2FCi_5mrhkChdMiDXLLxA1xwj7XUc"
    settings.NEW_MAIL_WEBHOOK_TOKEN = HOOK_TOKEN
    settings.WEBMAIL_URL = "https://mail.bthinkx.test/SOGo"


@pytest.fixture
def client():
    from rest_framework.test import APIClient

    return APIClient()


@pytest.fixture
def sent(monkeypatch):
    calls = []

    def fake_webpush(**kwargs):
        calls.append({**kwargs, "payload": json.loads(kwargs["data"])})

    monkeypatch.setattr("pywebpush.webpush", fake_webpush)
    return calls


def mailbox_for(business, domain, address):
    local = address.split("@")[0]
    return Mailbox.objects.create(
        business=business, domain=domain, local_part=local, email=address, quota_mb=100, status=Mailbox.Status.ACTIVE
    )


def subscribe(client, endpoint=ENDPOINT):
    return client.post("/api/notifications/subscriptions/", {"endpoint": endpoint, "keys": KEYS}, format="json")


def hook(client, **body):
    return client.post("/api/push/new-mail/", body, format="json", HTTP_AUTHORIZATION=f"Bearer {HOOK_TOKEN}")


def test_config_exposes_only_the_public_key(biz_client):
    data = biz_client.get("/api/notifications/config/").json()
    assert data["enabled"] is True
    assert "private" not in json.dumps(data).lower()


def test_subscribe_validates_push_service(biz_client):
    assert subscribe(biz_client).status_code == 201
    bad = subscribe(biz_client, "https://internal.example.com/hook")
    assert bad.status_code == 400
    assert subscribe(biz_client, "http://fcm.googleapis.com/x").status_code == 400
    assert subscribe(biz_client, "https://fcm.googleapis.com.evil.com/x").status_code == 400
    assert PushSubscription.objects.count() == 1


def test_resubscribe_moves_device_to_current_user(biz_client, ops_client, biz_admin, ops_admin):
    subscribe(biz_client)
    subscribe(ops_client)
    assert PushSubscription.objects.get().user == ops_admin


def test_unsubscribe_only_removes_own_device(biz_client, other_client):
    subscribe(biz_client)
    other_client.delete("/api/notifications/subscriptions/", {"endpoint": ENDPOINT}, format="json")
    assert PushSubscription.objects.count() == 1
    biz_client.delete("/api/notifications/subscriptions/", {"endpoint": ENDPOINT}, format="json")
    assert PushSubscription.objects.count() == 0


def test_test_notification_reaches_device(biz_client, sent):
    assert biz_client.post("/api/notifications/test/").status_code == 409
    subscribe(biz_client)
    assert biz_client.post("/api/notifications/test/").status_code == 200
    payload = sent[0]["payload"]
    assert payload["title"] == "Notifications are on"
    assert payload["center"] == "ABC Traders"


def test_webhook_requires_token(client, db):
    resp = client.post("/api/push/new-mail/", {"recipient": "a@b.c"}, format="json")
    assert resp.status_code == 401
    resp = client.post(
        "/api/push/new-mail/", {"recipient": "a@b.c"}, format="json", HTTP_AUTHORIZATION="Bearer wrong"
    )
    assert resp.status_code == 401


def test_webhook_disabled_without_token(client, settings):
    settings.NEW_MAIL_WEBHOOK_TOKEN = ""
    assert hook(client, recipient="a@b.c").status_code == 404


def test_new_mail_notifies_owner_with_gmail_style_payload(client, biz_client, biz_admin, business, domain, sent):
    mailbox_for(business, domain, biz_admin.email)
    subscribe(biz_client)
    resp = hook(client, recipient=biz_admin.email, sender='"Ravi Kumar" <ravi@example.com>', subject="Invoice\nMarch")
    assert resp.status_code == 202
    assert len(sent) == 1
    payload = sent[0]["payload"]
    assert payload["title"] == "Ravi Kumar"
    assert payload["body"] == "Invoice March"  # control characters stripped
    assert payload["account"] == biz_admin.email
    assert payload["center"] == "ABC Traders"
    assert payload["url"] == "https://mail.bthinkx.test/SOGo"
    assert sent[0]["headers"]["Urgency"] == "high"


def test_new_mail_accepts_dovecot_format(client, biz_client, biz_admin, business, domain, sent):
    mailbox_for(business, domain, biz_admin.email)
    subscribe(biz_client)
    hook(client, user=biz_admin.email, **{"from": "a@example.com"}, subject="Hi")
    assert sent[0]["payload"]["title"] == "a@example.com"


def test_new_mail_only_goes_to_watchers_in_same_business(
    client, biz_client, other_client, business, domain, biz_admin, other_admin, sent
):
    mailbox_for(business, domain, "sales@abctraders.com")
    subscribe(biz_client, ENDPOINT + "1")
    subscribe(other_client, ENDPOINT + "2")
    hook(client, recipient="sales@abctraders.com", sender="x@y.com", subject="s")
    assert sent == []  # nobody watches sales@ yet

    box = Mailbox.objects.get(email="sales@abctraders.com")
    resp = biz_client.patch("/api/notifications/preferences/", {"watched_mailboxes": [box.pk]}, format="json")
    assert resp.json()["watched_mailboxes"] == [box.pk]
    # another tenant cannot watch it, even by guessing the id
    other_client.patch("/api/notifications/preferences/", {"watched_mailboxes": [box.pk]}, format="json")
    assert not MailWatch.objects.filter(user=other_admin).exists()

    hook(client, recipient="sales@abctraders.com", sender="x@y.com", subject="s")
    assert [c["subscription_info"]["endpoint"] for c in sent] == [ENDPOINT + "1"]


def test_category_can_be_switched_off(client, biz_client, biz_admin, business, domain, sent):
    mailbox_for(business, domain, biz_admin.email)
    subscribe(biz_client)
    biz_client.patch("/api/notifications/preferences/", {"new_mail": False}, format="json")
    hook(client, recipient=biz_admin.email, sender="x@y.com", subject="s")
    assert sent == []


def test_unknown_recipient_is_ignored(client, sent, db):
    assert hook(client, recipient="nobody@nowhere.test").status_code == 202
    assert sent == []


def test_rate_cap_protects_push_service(client, biz_client, biz_admin, business, domain, sent, settings):
    settings.PUSH_MAIL_RATE_PER_MINUTE = 3
    mailbox_for(business, domain, biz_admin.email)
    subscribe(biz_client)
    for i in range(6):
        hook(client, recipient=biz_admin.email, sender="x@y.com", subject=str(i))
    assert len(sent) == 3


def test_gone_subscription_is_removed(biz_client, monkeypatch):
    class Resp:
        status_code = 410

    def gone(**kwargs):
        raise WebPushException("gone", response=Resp())

    monkeypatch.setattr("pywebpush.webpush", gone)
    subscribe(biz_client)
    biz_client.post("/api/notifications/test/")
    assert PushSubscription.objects.count() == 0


def test_security_event_notifies_staff_and_own_business_only(
    biz_client, other_client, staff_client, business, domain, sent
):
    from apps.security.models import SecurityEvent
    from apps.security.services import record_event

    box = mailbox_for(business, domain, "sales@abctraders.com")
    subscribe(biz_client, ENDPOINT + "biz")
    subscribe(other_client, ENDPOINT + "other")
    subscribe(staff_client, ENDPOINT + "staff")
    record_event(
        event_type=SecurityEvent.EventType.SPAM_ACTIVITY,
        severity=SecurityEvent.Severity.HIGH,
        mailbox=box,
        description="Outbound spam detected",
    )
    endpoints = sorted(c["subscription_info"]["endpoint"] for c in sent)
    assert endpoints == [ENDPOINT + "biz", ENDPOINT + "staff"]


def test_system_alerts_only_reach_staff(biz_client, staff_client, sent):
    from apps.notifications.service import raise_alert

    subscribe(biz_client, ENDPOINT + "biz")
    subscribe(staff_client, ENDPOINT + "staff")
    raise_alert("disk-full", "Mail disk almost full", "Disk at 91%", severity="CRITICAL")
    assert [c["subscription_info"]["endpoint"] for c in sent] == [ENDPOINT + "staff"]


def test_push_disabled_without_keys(biz_client, settings):
    settings.VAPID_PUBLIC_KEY = settings.VAPID_PRIVATE_KEY = ""
    assert biz_client.get("/api/notifications/config/").json()["enabled"] is False
    assert subscribe(biz_client).status_code == 503


def test_inactive_user_gets_nothing(business, domain, sent):
    user = make_user("gone@abctraders.com", Role.BUSINESS_ADMIN, business)
    mailbox_for(business, domain, user.email)
    client = client_for(user)
    subscribe(client)
    user.is_active = False
    user.save()
    from apps.notifications.push import notify_new_mail

    assert notify_new_mail(user.email, "a@b.c", "s") == 0


def test_encoded_headers_are_decoded(client, biz_client, biz_admin, business, domain, sent):
    mailbox_for(business, domain, biz_admin.email)
    subscribe(biz_client)
    hook(client, recipient=biz_admin.email, sender="=?utf-8?B?UmF2aSDgpJXgpYHgpK7gpL7gpLA=?= <r@example.com>",
         subject="=?utf-8?Q?Caf=C3=A9_menu?=")
    assert sent[0]["payload"]["body"] == "Café menu"
    assert sent[0]["payload"]["title"].startswith("Ravi")
