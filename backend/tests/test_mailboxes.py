import pytest

from apps.audit.models import AuditLog
from apps.mailboxes.models import Alias, Mailbox

pytestmark = pytest.mark.django_db


def create(client, domain, local="sales", **extra):
    return client.post("/api/mailboxes/", {"domain": domain.pk, "local_part": local, **extra}, format="json")


def test_create_mailbox(biz_client, domain, mailcow):
    resp = create(biz_client, domain, "Sales", display_name="Sales Department", quota_mb=1024)
    assert resp.status_code == 201, resp.json()
    body = resp.json()
    assert body["email"] == "sales@abctraders.com"
    assert body["status"] == "ACTIVE"
    password = body["temporary_password"]
    assert len(password) >= 16
    assert resp["Cache-Control"] == "no-store"

    remote = mailcow.mailboxes["sales@abctraders.com"]
    assert remote["_password"] == password
    assert remote["attributes"]["force_pw_update"] == "1"
    assert remote["quota"] == 1024 * 1024 * 1024
    assert mailcow.rate_limits["sales@abctraders.com"] == {"rl_value": "20", "rl_frame": "h"}

    # The password is never persisted by the platform (not in the row, not in the audit log)
    mailbox = Mailbox.objects.get(email="sales@abctraders.com")
    for field in mailbox._meta.concrete_fields:
        assert password not in str(getattr(mailbox, field.attname))
    for entry in AuditLog.objects.all():
        assert password not in str(entry.metadata)
    assert "temporary_password" not in biz_client.get(f"/api/mailboxes/{mailbox.pk}/").json()


def test_default_quota_from_plan(biz_client, domain, plan):
    assert create(biz_client, domain).json()["quota_mb"] == plan.default_mailbox_quota_mb


@pytest.mark.parametrize("local", ["", ".dot", "dot.", "a..b", "spa ce", "x" * 65, "sales@evil.com"])
def test_invalid_local_parts(biz_client, domain, local):
    assert create(biz_client, domain, local).status_code == 400


def test_reserved_local_part(biz_client, domain):
    assert create(biz_client, domain, "postmaster").status_code == 400


def test_duplicate_mailbox(biz_client, domain):
    assert create(biz_client, domain).status_code == 201
    assert create(biz_client, domain, "SALES").status_code == 409


def test_mailbox_count_limit(biz_client, domain, plan):
    for i in range(plan.max_mailboxes):
        assert create(biz_client, domain, f"u{i}", quota_mb=10).status_code == 201
    resp = create(biz_client, domain, "extra", quota_mb=10)
    assert resp.status_code == 409 and resp.json()["code"] == "quota_exceeded"


def test_per_mailbox_and_total_storage_limits(biz_client, domain, plan):
    resp = create(biz_client, domain, "big", quota_mb=plan.max_mailbox_quota_mb + 1)
    assert resp.status_code == 409
    assert create(biz_client, domain, "a", quota_mb=2048).status_code == 201
    assert create(biz_client, domain, "b", quota_mb=2048).status_code == 201
    resp = create(biz_client, domain, "c", quota_mb=1)  # 4096 MB total already allocated
    assert resp.status_code == 409
    assert "storage" in resp.json()["detail"].lower()


def test_domain_must_be_provisioned(biz_client, business):
    from apps.domains.services import create_domain

    pending = create_domain(business=business, name="pending.com")
    resp = create(biz_client, pending)
    assert resp.status_code == 400
    assert "not ready" in resp.json()["detail"]


def test_mailcow_failure_leaves_no_local_row(biz_client, domain, mailcow):
    mailcow.fail("POST", "add/mailbox", 503)
    resp = create(biz_client, domain)
    assert resp.status_code == 502
    assert not Mailbox.objects.filter(email="sales@abctraders.com").exists()


def test_partial_failure_is_compensated(biz_client, domain, mailcow):
    mailcow.fail("POST", "edit/rl-mbox", "danger")
    resp = create(biz_client, domain)
    assert resp.status_code == 502
    assert not Mailbox.objects.filter(email="sales@abctraders.com").exists()
    assert "sales@abctraders.com" not in mailcow.mailboxes  # rolled back remotely
    assert mailcow.calls_to("delete/mailbox")


def test_remote_conflict_maps_to_409(biz_client, domain, mailcow):
    mailcow.mailboxes["sales@abctraders.com"] = {"username": "sales@abctraders.com", "domain": "abctraders.com"}
    resp = create(biz_client, domain)
    assert resp.status_code == 409
    assert not Mailbox.objects.exists()


def test_mailcow_auth_failure_alerts(biz_client, domain, settings):
    from apps.notifications.models import Alert

    settings.MAILCOW_API_KEY = "wrong"
    resp = create(biz_client, domain)
    assert resp.status_code == 502
    assert Alert.objects.filter(key="mailcow-auth").exists()


@pytest.fixture
def mailbox(biz_client, domain):
    resp = create(biz_client, domain)
    return Mailbox.objects.get(pk=resp.json()["id"])


def test_suspend_disable_activate(biz_client, mailbox, mailcow):
    remote = mailcow.mailboxes[mailbox.email]
    assert biz_client.post(f"/api/mailboxes/{mailbox.pk}/suspend/").json()["status"] == "SUSPENDED"
    assert remote["active"] == "2"  # login blocked, mail still delivered
    assert biz_client.post(f"/api/mailboxes/{mailbox.pk}/disable/").json()["status"] == "DISABLED"
    assert remote["active"] == "0"
    assert biz_client.post(f"/api/mailboxes/{mailbox.pk}/activate/").json()["status"] == "ACTIVE"
    assert remote["active"] == "1"
    actions = list(AuditLog.objects.filter(object_id=str(mailbox.pk)).values_list("action", flat=True))
    assert {"mailbox.suspended", "mailbox.disabled", "mailbox.activated"} <= set(actions)


def test_reset_password(biz_client, mailbox, mailcow):
    resp = biz_client.post(f"/api/mailboxes/{mailbox.pk}/reset-password/")
    pw = resp.json()["temporary_password"]
    assert mailcow.mailboxes[mailbox.email]["_password"] == pw
    assert mailcow.mailboxes[mailbox.email]["attributes"]["force_pw_update"] == "1"


def test_update_quota_and_name(biz_client, mailbox, mailcow):
    resp = biz_client.patch(f"/api/mailboxes/{mailbox.pk}/", {"quota_mb": 2048, "display_name": "Sales"}, format="json")
    assert resp.status_code == 200
    assert mailcow.mailboxes[mailbox.email]["quota"] == 2048 * 1024 * 1024
    assert mailcow.mailboxes[mailbox.email]["name"] == "Sales"


def test_quota_cannot_shrink_below_usage(biz_client, mailbox):
    Mailbox.objects.filter(pk=mailbox.pk).update(used_bytes=900 * 1024 * 1024)
    resp = biz_client.patch(f"/api/mailboxes/{mailbox.pk}/", {"quota_mb": 100}, format="json")
    assert resp.status_code == 400


def test_outbound_suspend_and_staff_restore(biz_client, staff_client, mailbox, mailcow):
    resp = biz_client.post(f"/api/mailboxes/{mailbox.pk}/suspend-outbound/", {"reason": "Phishing"}, format="json")
    assert resp.json()["outbound_suspended"] is True
    assert resp.json()["status"] == "ACTIVE"  # incoming mail continues
    assert mailcow.mailboxes[mailbox.email]["attributes"]["smtp_access"] == "0"
    resp = staff_client.post(f"/api/mailboxes/{mailbox.pk}/restore-outbound/", {"reason": "Cleaned"}, format="json")
    assert resp.json()["outbound_suspended"] is False
    assert mailcow.mailboxes[mailbox.email]["attributes"]["smtp_access"] == "1"


def test_staff_sets_custom_limits(staff_client, mailbox, mailcow):
    resp = staff_client.patch(
        f"/api/mailboxes/{mailbox.pk}/", {"outbound_limit_per_hour": 300, "outbound_limit_per_day": 2000}, format="json"
    )
    assert resp.status_code == 200
    assert mailcow.rate_limits[mailbox.email]["rl_value"] == "300"


def test_delete_mailbox(biz_client, mailbox, mailcow):
    assert biz_client.delete(f"/api/mailboxes/{mailbox.pk}/").status_code == 204
    assert mailbox.email not in mailcow.mailboxes
    assert not Mailbox.objects.filter(pk=mailbox.pk).exists()


def test_delete_failure_restores_status(biz_client, mailbox, mailcow):
    mailcow.fail("POST", "delete/mailbox", 500)
    assert biz_client.delete(f"/api/mailboxes/{mailbox.pk}/").status_code == 502
    assert Mailbox.objects.get(pk=mailbox.pk).status == "ACTIVE"


# ----------------------------------------------------------------------------- aliases
def test_alias_lifecycle(biz_client, domain, mailbox, mailcow):
    resp = biz_client.post(
        "/api/aliases/",
        {"domain": domain.pk, "local_part": "hello", "destinations": ["sales@abctraders.com", "SALES@abctraders.com"]},
        format="json",
    )
    assert resp.status_code == 201, resp.json()
    alias = Alias.objects.get(source_address="hello@abctraders.com")
    assert alias.destinations == ["sales@abctraders.com"]
    remote = mailcow.aliases[int(alias.mailcow_id)]
    assert remote["goto"] == "sales@abctraders.com"

    resp = biz_client.patch(
        f"/api/aliases/{alias.pk}/", {"destinations": ["a@gmail.com"], "status": "DISABLED"}, format="json"
    )
    assert resp.status_code == 200
    assert remote["goto"] == "a@gmail.com" and remote["active"] == "0"

    assert biz_client.delete(f"/api/aliases/{alias.pk}/").status_code == 204
    assert not mailcow.aliases


def test_alias_conflicts_with_mailbox(biz_client, domain, mailbox):
    resp = biz_client.post(
        "/api/aliases/", {"domain": domain.pk, "local_part": "sales", "destinations": ["x@y.com"]}, format="json"
    )
    assert resp.status_code == 409


def test_alias_validation(biz_client, domain):
    resp = biz_client.post(
        f"/api/domains/{domain.pk}/aliases/",
        {"local_part": "loop", "destinations": ["loop@abctraders.com"]},
        format="json",
    )
    assert resp.status_code == 400
    resp = biz_client.post(
        f"/api/domains/{domain.pk}/aliases/", {"local_part": "x", "destinations": ["nope"]}, format="json"
    )
    assert resp.status_code == 400


def test_postmaster_allowed_as_alias(biz_client, domain):
    resp = biz_client.post(
        f"/api/domains/{domain.pk}/aliases/",
        {"local_part": "postmaster", "destinations": ["it@abctraders.com"]},
        format="json",
    )
    assert resp.status_code == 201
