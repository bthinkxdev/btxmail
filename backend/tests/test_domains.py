import pytest

from apps.domains import services
from apps.domains.models import Domain
from apps.mailboxes.models import Mailbox
from apps.notifications.models import Alert

pytestmark = pytest.mark.django_db


def create(client, name):
    return client.post("/api/domains/", {"name": name}, format="json")


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "localhost",
        "http://abc.com",
        "a b.com",
        "-abc.com",
        "abc..com",
        "user@abc.com",
        "1.2.3.4",
        "mail.bthinkx.test",
    ],
)
def test_rejects_invalid_domain_names(biz_client, bad):
    resp = create(biz_client, bad)
    assert resp.status_code == 400, bad


def test_normalizes_and_rejects_duplicates(biz_client, other_client):
    resp = create(biz_client, "  ABCTraders.COM. ")
    assert resp.status_code == 201
    assert resp.json()["name"] == "abctraders.com"
    assert resp.json()["status"] == "PENDING_VERIFICATION"
    assert resp.json()["verification"]["record_name"] == "_bthinkx-verification.abctraders.com"
    assert create(other_client, "abctraders.com").status_code == 409


def test_idn_domain(biz_client):
    resp = create(biz_client, "bücher.de")
    assert resp.status_code == 201
    assert resp.json()["name"] == "xn--bcher-kva.de"


def test_plan_domain_limit(biz_client, plan):
    for i in range(plan.max_domains):
        assert create(biz_client, f"d{i}.com").status_code == 201
    resp = create(biz_client, "one-too-many.com")
    assert resp.status_code == 409
    assert resp.json()["code"] == "quota_exceeded"


def test_full_domain_lifecycle(biz_client, fake_dns, mailcow, settings):
    domain_id = create(biz_client, "abctraders.com").json()["id"]

    # 1. verification fails until the TXT record exists; nothing is created in Mailcow
    resp = biz_client.post(f"/api/domains/{domain_id}/verify/")
    assert resp.json()["result"]["status"] == "FAIL"
    assert "abctraders.com" not in mailcow.domains

    # 2. publish the TXT record → verified → provisioned (Celery eager) → DNS_PENDING
    token = Domain.objects.get(pk=domain_id).verification_token
    fake_dns.set_txt("_bthinkx-verification.abctraders.com", token)
    resp = biz_client.post(f"/api/domains/{domain_id}/verify/")
    assert resp.json()["result"]["status"] == "PASS"
    domain = Domain.objects.get(pk=domain_id)
    assert domain.status == Domain.Status.DNS_PENDING
    assert domain.mailcow_provisioned
    assert mailcow.domains["abctraders.com"]["mailboxes"] == "3"
    assert domain.dkim_public_record == mailcow.dkim["abctraders.com"]["dkim_txt"]
    purposes = {r["purpose"] for r in resp.json()["domain"]["dns_records"]}
    assert {"MX", "SPF", "DKIM", "DMARC"} <= purposes

    # 3. customer publishes MX/SPF/DKIM/DMARC → domain becomes ACTIVE
    fake_dns.publish_domain("abctraders.com", mail_host=settings.MAIL_HOSTNAME, dkim_txt=domain.dkim_public_record)
    resp = biz_client.post(f"/api/domains/{domain_id}/check-dns/")
    body = resp.json()
    assert body["status"] == "ACTIVE"
    assert body["dns_status"]["mx_status"] == "PASS"
    assert body["dns_status"]["spf_status"] == "PASS"
    assert body["dns_status"]["dkim_status"] == "PASS"
    assert body["dns_status"]["dmarc_status"] == "PASS"
    assert body["dns_status"]["ptr_status"] == "PASS"

    # 4. delete removes it from Mailcow too
    assert biz_client.delete(f"/api/domains/{domain_id}/").status_code == 204
    assert "abctraders.com" not in mailcow.domains
    assert "abctraders.com" not in mailcow.dkim


def test_provisioning_retries_then_fails_with_alert(biz_client, fake_dns, mailcow, monkeypatch):
    from apps.domains import tasks

    monkeypatch.setattr(tasks, "RETRY_COUNTDOWNS", ())
    domain_id = create(biz_client, "flaky.com").json()["id"]
    fake_dns.set_txt("_bthinkx-verification.flaky.com", Domain.objects.get(pk=domain_id).verification_token)
    mailcow.fail("POST", "add/domain", 503)
    biz_client.post(f"/api/domains/{domain_id}/verify/")
    domain = Domain.objects.get(pk=domain_id)
    assert domain.status == Domain.Status.PROVISIONING_FAILED
    assert "503" in domain.last_error
    assert Alert.objects.filter(key=f"domain-provision-failed:{domain_id}").exists()


def test_provisioning_is_idempotent_when_domain_exists(business, fake_dns, mailcow):
    domain = services.create_domain(business=business, name="existing.com")
    mailcow.domains["existing.com"] = {"domain_name": "existing.com"}
    fake_dns.set_txt("_bthinkx-verification.existing.com", domain.verification_token)
    services.verify_domain(domain)
    domain.refresh_from_db()
    assert domain.status == Domain.Status.DNS_PENDING


def test_staff_retry_after_failure(staff_client, business, fake_dns, mailcow, monkeypatch):
    from apps.domains import tasks

    monkeypatch.setattr(tasks, "RETRY_COUNTDOWNS", ())
    domain = services.create_domain(business=business, name="retry.com")
    fake_dns.set_txt("_bthinkx-verification.retry.com", domain.verification_token)
    mailcow.fail("POST", "add/domain", 500)
    services.verify_domain(domain)
    assert Domain.objects.get(pk=domain.pk).status == Domain.Status.PROVISIONING_FAILED
    resp = staff_client.post(f"/api/domains/{domain.pk}/retry-provisioning/")
    assert resp.status_code == 200
    assert Domain.objects.get(pk=domain.pk).status == Domain.Status.DNS_PENDING


def test_manual_verification_staff_only(biz_client, staff_client, business):
    domain = services.create_domain(business=business, name="manual.com")
    assert biz_client.post(f"/api/domains/{domain.pk}/verify-manually/").status_code == 403
    resp = staff_client.post(f"/api/domains/{domain.pk}/verify-manually/", {"reason": "Phone confirmed"}, format="json")
    assert resp.status_code == 200
    assert Domain.objects.get(pk=domain.pk).verification_method == "MANUAL"


def test_delete_blocked_while_mailboxes_exist(biz_client, business, domain):
    Mailbox.objects.create(
        business=business, domain=domain, local_part="a", email="a@abctraders.com", quota_mb=1, status="ACTIVE"
    )
    resp = biz_client.delete(f"/api/domains/{domain.pk}/")
    assert resp.status_code == 409


def test_dns_regression_alerts(business, domain, fake_dns, settings):
    fake_dns.publish_domain(domain.name, mail_host=settings.MAIL_HOSTNAME, dkim_txt=domain.dkim_public_record)
    assert services.refresh_dns_status(domain).is_ready
    fake_dns.set_mx(domain.name, "mx.someone-else.com")
    services.refresh_dns_status(domain)
    assert Alert.objects.filter(key__startswith=f"dns-failure:{domain.pk}").exists()


def test_transient_dns_failure_is_unknown_not_fail(business, domain, fake_dns):
    fake_dns.broken.add((domain.name, "MX"))
    status = services.refresh_dns_status(domain)
    assert status.mx_status == "UNKNOWN"


def test_suspend_and_activate_domain(staff_client, domain, mailcow):
    assert staff_client.post(f"/api/domains/{domain.pk}/suspend/").json()["status"] == "SUSPENDED"
    assert mailcow.domains[domain.name]["active"] == "0"
    resp = staff_client.post(f"/api/domains/{domain.pk}/activate/")
    assert resp.json()["status"] in ("ACTIVE", "DNS_PENDING")
    assert mailcow.domains[domain.name]["active"] == "1"


def test_nested_business_domains_route(staff_client, business):
    resp = staff_client.post(f"/api/businesses/{business.pk}/domains/", {"name": "nested.com"}, format="json")
    assert resp.status_code == 201
    listing = staff_client.get(f"/api/businesses/{business.pk}/domains/").json()
    assert [d["name"] for d in listing["results"]] == ["nested.com"]


def test_verification_expiry(biz_client, business, settings):
    from datetime import timedelta

    from django.utils import timezone

    domain = services.create_domain(business=business, name="old.com")
    Domain.objects.filter(pk=domain.pk).update(
        verification_started_at=timezone.now() - timedelta(days=settings.DOMAIN_VERIFICATION_EXPIRY_DAYS + 1)
    )
    resp = biz_client.post(f"/api/domains/{domain.pk}/verify/")
    assert resp.json()["code"] == "verification_expired"
    resp = biz_client.post(f"/api/domains/{domain.pk}/regenerate-token/")
    assert resp.status_code == 200
    assert resp.json()["verification"]["record_value"] != domain.verification_token
