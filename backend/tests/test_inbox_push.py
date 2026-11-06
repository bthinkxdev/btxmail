"""New-mail push for people who only use webmail: subscriptions via the bridge token, and message previews."""

import json

import pytest
from rest_framework.test import APIClient

from apps.notifications.models import InboxPushSubscription
from apps.notifications.push import parse_raw_message

from .test_push import ENDPOINT, HOOK_TOKEN, KEYS, mailbox_for

AUTH = {"HTTP_AUTHORIZATION": f"Bearer {HOOK_TOKEN}"}


@pytest.fixture(autouse=True)
def push_on(settings):
    settings.VAPID_PUBLIC_KEY = (
        "BLNssA8rX6XZowMwwrcn5-iGQT0GR_T_fnCmyVV748AUOdSDwOnkwkpNk-peGJj3AFIA7TFNfd-3wN6jLOMpqI4"
    )
    settings.VAPID_PRIVATE_KEY = "MPoh9nawGCA-YX2FCi_5mrhkChdMiDXLLxA1xwj7XUc"
    settings.NEW_MAIL_WEBHOOK_TOKEN = HOOK_TOKEN


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture
def sent(monkeypatch):
    calls = []

    def fake_webpush(**kwargs):
        calls.append({**kwargs, "payload": json.loads(kwargs["data"])})

    monkeypatch.setattr("pywebpush.webpush", fake_webpush)
    return calls


def inbox_subscribe(client, mailbox="sales@abctraders.com", endpoint=ENDPOINT, **extra):
    return client.post(
        "/api/push/inbox/subscribe/",
        {"mailbox": mailbox, "subscription": {"endpoint": endpoint, "keys": KEYS}, **extra},
        format="json",
        **AUTH,
    )


def raw_hook(client, raw: bytes, recipient="sales@abctraders.com", **headers):
    return client.post(
        "/api/push/new-mail-raw/",
        data=raw,
        content_type="message/rfc822",
        HTTP_X_RECIPIENT=recipient,
        **{**AUTH, **headers},
    )


PLAIN = (
    b"From: =?utf-8?q?Ravi_Kumar?= <ravi@example.com>\r\n"
    b"To: sales@abctraders.com\r\n"
    b"Subject: =?utf-8?q?Quarterly_invoice?=\r\n"
    b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
    b"Hi team,\r\n\r\nPlease find the March invoice attached. Payment is due on Friday.\r\n"
    b"> older quoted text that must not appear\r\n"
)

HTML = (
    b"From: News <news@example.com>\r\nSubject: Offer\r\nContent-Type: text/html; charset=utf-8\r\n\r\n"
    b"<html><head><title>x</title><style>p{color:red}</style></head>"
    b"<body><script>alert(1)</script><p>Big <b>sale</b> today</p> <a href='https://t.co/x'>link</a></body></html>"
)


def test_parse_plain_message_skips_quotes():
    sender, subject, preview = parse_raw_message(PLAIN)
    assert "Ravi Kumar" in sender
    assert subject == "Quarterly invoice"
    assert preview.startswith("Hi team, Please find the March invoice")
    assert "quoted" not in preview


def test_parse_html_message_strips_markup_and_scripts():
    _, _, preview = parse_raw_message(HTML)
    assert preview == "Big sale today link"  # markup, scripts and styles removed; visible text kept


def test_parse_garbage_never_raises():
    for raw in (b"\x00\xff not an email", b"", b"Content-Type: multipart/mixed; boundary=x\r\n\r\n--x\r\n"):
        _sender, _subject, preview = parse_raw_message(raw)
        assert isinstance(preview, str) and len(preview) <= 140


def test_inbox_endpoints_need_the_token(client, db):
    resp = client.post("/api/push/inbox/subscribe/", {"mailbox": "a@b.c"}, format="json")
    assert resp.status_code == 401
    assert client.get("/api/push/inbox/config/").status_code == 401
    assert client.get("/api/push/inbox/config/", **AUTH).json()["enabled"] is True


def test_subscribe_validates_mailbox_and_push_service(client, business, domain):
    mailbox_for(business, domain, "sales@abctraders.com")
    assert inbox_subscribe(client).status_code == 201
    assert inbox_subscribe(client, mailbox="nobody@abctraders.com", endpoint=ENDPOINT + "2").status_code == 404
    assert inbox_subscribe(client, endpoint="https://internal.example.com/x").status_code == 400
    assert InboxPushSubscription.objects.count() == 1


def test_subscribe_keeps_only_newest_devices(client, business, domain):
    mailbox_for(business, domain, "sales@abctraders.com")
    for i in range(12):
        assert inbox_subscribe(client, endpoint=f"{ENDPOINT}{i}").status_code == 201
    assert InboxPushSubscription.objects.count() == 10


def test_unsubscribe_removes_device(client, business, domain):
    mailbox_for(business, domain, "sales@abctraders.com")
    inbox_subscribe(client)
    resp = client.post(
        "/api/push/inbox/unsubscribe/", {"mailbox": "sales@abctraders.com", "endpoint": ENDPOINT}, format="json", **AUTH
    )
    assert resp.json() == {"removed": True}
    assert InboxPushSubscription.objects.count() == 0


def test_raw_hook_requires_token_and_recipient(client, db):
    assert client.post("/api/push/new-mail-raw/", data=PLAIN, content_type="message/rfc822").status_code == 401
    resp = client.post("/api/push/new-mail-raw/", data=PLAIN, content_type="message/rfc822", **AUTH)
    assert resp.status_code == 400


def test_new_mail_reaches_inbox_device_with_subject_and_preview(client, business, domain, sent):
    mailbox_for(business, domain, "sales@abctraders.com")
    inbox_subscribe(client)
    assert raw_hook(client, PLAIN).status_code == 202
    assert len(sent) == 1
    payload = sent[0]["payload"]
    assert payload["title"] == "Ravi Kumar"
    assert payload["body"] == "Quarterly invoice"
    assert payload["preview"].startswith("Hi team, Please find the March invoice")
    assert payload["account"] == "sales@abctraders.com"
    assert payload["url"] == "/SOGo/"
    assert sent[0]["headers"]["Urgency"] == "high"
    assert "invoice" in json.dumps(payload)


def test_inbox_device_only_gets_its_own_mailbox(client, business, domain, sent):
    mailbox_for(business, domain, "sales@abctraders.com")
    mailbox_for(business, domain, "info@abctraders.com")
    inbox_subscribe(client, mailbox="sales@abctraders.com", endpoint=ENDPOINT + "s")
    inbox_subscribe(client, mailbox="info@abctraders.com", endpoint=ENDPOINT + "i")
    raw_hook(client, PLAIN, recipient="info@abctraders.com")
    assert len(sent) == 1
    assert sent[0]["subscription_info"]["endpoint"] == ENDPOINT + "i"


def test_gone_inbox_subscription_is_removed(client, business, domain, monkeypatch):
    from pywebpush import WebPushException

    class Resp:
        status_code = 410

    def gone(**kwargs):
        raise WebPushException("gone", response=Resp())

    monkeypatch.setattr("pywebpush.webpush", gone)
    mailbox_for(business, domain, "sales@abctraders.com")
    inbox_subscribe(client)
    raw_hook(client, PLAIN)
    assert InboxPushSubscription.objects.count() == 0


def test_json_hook_accepts_a_preview(client, business, domain, sent):
    mailbox_for(business, domain, "sales@abctraders.com")
    inbox_subscribe(client)
    client.post(
        "/api/push/new-mail/",
        {"recipient": "sales@abctraders.com", "sender": "a@b.com", "subject": "Hi", "preview": "Hello there"},
        format="json",
        **AUTH,
    )
    assert sent[0]["payload"]["preview"] == "Hello there"
