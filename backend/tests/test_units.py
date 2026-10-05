"""Unit tests: Mailcow client protocol handling, DNS logic, helpers, health endpoints."""

import pytest
import responses

from apps.core.utils import generate_password
from apps.domains import dns_checks
from apps.mailcow import mailboxes as mc_mailboxes
from apps.mailcow.client import MailcowClient
from apps.mailcow.exceptions import MailcowAPIError, MailcowAuthError, MailcowNotConfigured, MailcowUnavailable

from .fake_mailcow import BASE


# ----------------------------------------------------------------------------- client
@pytest.fixture
def raw():
    """A bare responses mock (no fake server) for protocol edge cases."""
    with responses.RequestsMock() as rsps:
        yield rsps


@pytest.fixture(autouse=True)
def mailcow():  # override the autouse fake server for this module
    yield None


def client():
    return MailcowClient(BASE, "key", timeout=2)


def test_danger_response_raises_with_codes(raw):
    raw.add(responses.POST, f"{BASE}/api/v1/add/mailbox", json=[{"type": "danger", "msg": ["object_exists", "a@b.c"]}])
    with pytest.raises(MailcowAPIError) as exc:
        client().mutate("add/mailbox", {})
    assert exc.value.has_code("object_exists")


def test_mixed_success_and_error_raises(raw):
    raw.add(
        responses.POST,
        f"{BASE}/api/v1/edit/mailbox",
        json=[{"type": "success", "msg": "ok"}, {"type": "error", "msg": "quota_exceeded"}],
    )
    with pytest.raises(MailcowAPIError):
        client().mutate("edit/mailbox", {})


def test_auth_errors(raw):
    raw.add(responses.GET, f"{BASE}/api/v1/get/domain/all", status=401, json={"type": "error"})
    with pytest.raises(MailcowAuthError):
        client().get("get/domain/all")


def test_non_json_and_5xx(raw):
    raw.add(responses.GET, f"{BASE}/api/v1/get/domain/all", body="<html>nope</html>")
    with pytest.raises(MailcowUnavailable):
        client().get("get/domain/all")
    raw.add(responses.POST, f"{BASE}/api/v1/add/domain", status=502)
    with pytest.raises(MailcowUnavailable):
        client().mutate("add/domain", {})


def test_empty_dict_normalized(raw):
    raw.add(responses.GET, f"{BASE}/api/v1/get/mailbox/all", json={})
    raw.add(responses.GET, f"{BASE}/api/v1/get/mailbox/x@y.z", json={})
    assert client().get_list("get/mailbox/all") == []
    assert client().get_object("get/mailbox/x@y.z") is None


def test_not_configured():
    with pytest.raises(MailcowNotConfigured):
        MailcowClient("", "").get("get/domain/all")


def test_api_key_header_sent(raw):
    raw.add(
        responses.GET,
        f"{BASE}/api/v1/get/status/version",
        json={"version": "x"},
        match=[responses.matchers.header_matcher({"X-API-Key": "key"})],
    )
    assert client().get("get/status/version") == {"version": "x"}


def test_parse_mailbox():
    parsed = mc_mailboxes.parse_mailbox(
        {
            "username": "A@B.com",
            "active_int": 2,
            "quota": "1048576",
            "quota_used": "10",
            "messages": "3",
            "last_imap_login": "1700000000",
            "last_smtp_login": "1700000500",
            "attributes": {"smtp_access": "0"},
        }
    )
    assert parsed["username"] == "a@b.com"
    assert parsed["active"] == "2"
    assert parsed["quota_bytes"] == 1048576
    assert parsed["smtp_access"] is False
    assert parsed["last_login_at"].timestamp() == 1700000500


# ----------------------------------------------------------------------------- DNS
def test_normalize_domain():
    assert dns_checks.normalize_domain("Example.COM.") == "example.com"
    with pytest.raises(ValueError):
        dns_checks.normalize_domain("example")


@pytest.mark.parametrize(
    "record,expected",
    [
        ("v=spf1 mx -all", "PASS"),
        ("v=spf1 include:_spf.google.com mx ~all", "WARN"),
        ("v=spf1 ip4:203.0.113.10 -all", "PASS"),
        ("v=spf1 a:mail.bthinkx.test -all", "PASS"),
        ("v=spf1 include:_spf.google.com -all", "FAIL"),
        ("v=spf1 mx +all", "WARN"),
    ],
)
def test_spf_evaluation(fake_dns, settings, record, expected):
    fake_dns.set_txt("x.com", record)
    assert dns_checks.check_spf("x.com").status == expected


def test_multiple_spf_records_fail(fake_dns):
    fake_dns.set_txt("x.com", "v=spf1 mx -all", "v=spf1 a -all")
    assert dns_checks.check_spf("x.com").status == "FAIL"


def test_mx_variants(fake_dns, settings):
    fake_dns.set_mx("x.com", settings.MAIL_HOSTNAME)
    assert dns_checks.check_mx("x.com").status == "PASS"
    fake_dns.set_mx("x.com", settings.MAIL_HOSTNAME, "backup.other.com")
    assert dns_checks.check_mx("x.com").status == "WARN"
    fake_dns.set_mx("x.com", "aspmx.l.google.com")
    assert dns_checks.check_mx("x.com").status == "FAIL"


def test_dkim_long_record_split_into_chunks(fake_dns):
    key = "MII" + "A" * 400
    expected = f"v=DKIM1;k=rsa;t=s;s=email;p={key}"
    fake_dns.set_txt("dkim._domainkey.x.com", f"v=DKIM1; k=rsa; p={key}")
    assert dns_checks.check_dkim("x.com", "dkim", expected).status == "PASS"
    fake_dns.set_txt("dkim._domainkey.x.com", "v=DKIM1; k=rsa; p=OTHER")
    assert dns_checks.check_dkim("x.com", "dkim", expected).status == "FAIL"


def test_dmarc(fake_dns):
    fake_dns.set_txt("_dmarc.x.com", "v=DMARC1; p=none")
    assert dns_checks.check_dmarc("x.com").status == "WARN"
    fake_dns.set_txt("_dmarc.x.com", "v=DMARC1; p=reject")
    assert dns_checks.check_dmarc("x.com").status == "PASS"


def test_ptr_mismatch(fake_dns):
    fake_dns.set_ptr("10.113.0.203.in-addr.arpa", "static.isp.example")
    assert dns_checks.check_ptr().status == "FAIL"


# ----------------------------------------------------------------------------- misc
def test_generate_password_strength():
    for _ in range(50):
        pw = generate_password()
        assert len(pw) == 20
        assert any(c.isupper() for c in pw) and any(c.islower() for c in pw) and any(c.isdigit() for c in pw)


@pytest.mark.django_db
def test_health_endpoints(client):
    assert client.get("/healthz").json() == {"status": "ok"}
    resp = client.get("/readyz")
    assert resp.status_code == 200 and resp.json()["checks"] == {"database": "ok", "cache": "ok"}
    assert client.get("/metrics", HTTP_X_FORWARDED_FOR="1.2.3.4").status_code == 403
    assert client.get("/metrics").status_code == 200  # REMOTE_ADDR 127.0.0.1 is allow-listed
    assert "X-Request-ID" in client.get("/healthz")


@pytest.mark.django_db
def test_unknown_api_route_is_404(client):
    assert client.get("/api/does-not-exist/").status_code == 404


@pytest.mark.django_db
def test_bootstrap_command(monkeypatch):
    from django.core.management import call_command

    from apps.accounts.models import User
    from apps.businesses.models import Plan

    monkeypatch.setenv("BOOTSTRAP_ADMIN_EMAIL", "Owner@BThinkX.com")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "Initial-Passw0rd-123")
    call_command("bootstrap")
    call_command("bootstrap")  # idempotent
    assert Plan.objects.count() == 3
    owner = User.objects.get(email="owner@bthinkx.com")
    assert owner.is_super_admin and owner.must_change_password
