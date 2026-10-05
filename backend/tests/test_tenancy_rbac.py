"""Business A must never be able to see or touch Business B (README §38/§39)."""

import pytest

from apps.accounts.models import Role, User
from apps.domains.models import Domain
from apps.mailboxes.models import Alias, Mailbox

pytestmark = pytest.mark.django_db


@pytest.fixture
def other_mailbox(other_business, other_domain):
    return Mailbox.objects.create(
        business=other_business,
        domain=other_domain,
        local_part="ceo",
        email="ceo@xyz.com",
        quota_mb=100,
        status="ACTIVE",
        mailcow_id="ceo@xyz.com",
    )


def test_lists_are_scoped(biz_client, domain, other_domain, other_mailbox):
    names = [d["name"] for d in biz_client.get("/api/domains/").json()["results"]]
    assert names == ["abctraders.com"]
    assert biz_client.get("/api/mailboxes/").json()["results"] == []
    businesses = biz_client.get("/api/businesses/").json()["results"]
    assert [b["name"] for b in businesses] == ["ABC Traders"]


@pytest.mark.parametrize(
    "method,suffix",
    [
        ("get", ""),
        ("delete", ""),
        ("post", "suspend/"),
        ("post", "reset-password/"),
        ("patch", ""),
    ],
)
def test_cannot_touch_other_tenant_mailbox(biz_client, other_mailbox, mailcow, method, suffix):
    url = f"/api/mailboxes/{other_mailbox.pk}/{suffix}"
    resp = getattr(biz_client, method)(url, {"display_name": "pwned"}, format="json")
    assert resp.status_code == 404
    assert Mailbox.objects.get(pk=other_mailbox.pk).display_name == ""
    assert not mailcow.calls_to("edit/mailbox") and not mailcow.calls_to("delete/mailbox")


def test_cannot_create_mailbox_on_other_tenant_domain(biz_client, other_domain, mailcow):
    resp = biz_client.post("/api/mailboxes/", {"domain": other_domain.pk, "local_part": "evil"}, format="json")
    assert resp.status_code == 404
    resp = biz_client.post(f"/api/domains/{other_domain.pk}/mailboxes/", {"local_part": "evil"}, format="json")
    assert resp.status_code == 404
    assert not mailcow.calls_to("add/mailbox")


def test_business_id_from_client_is_ignored(biz_client, business, other_business):
    resp = biz_client.post("/api/domains/", {"name": "sneaky.com", "business": other_business.pk}, format="json")
    assert resp.status_code == 201
    assert Domain.objects.get(name="sneaky.com").business_id == business.pk


def test_other_tenant_domain_and_business_hidden(biz_client, other_domain, other_business):
    assert biz_client.get(f"/api/domains/{other_domain.pk}/").status_code == 404
    assert biz_client.post(f"/api/domains/{other_domain.pk}/verify/").status_code == 404
    assert biz_client.get(f"/api/businesses/{other_business.pk}/").status_code == 404


def test_aliases_scoped(biz_client, other_business, other_domain):
    alias = Alias.objects.create(
        business=other_business,
        domain=other_domain,
        source_address="x@xyz.com",
        destinations=["ceo@xyz.com"],
        mailcow_id="9",
    )
    assert biz_client.get("/api/aliases/").json()["results"] == []
    assert biz_client.delete(f"/api/aliases/{alias.pk}/").status_code == 404


def test_audit_and_security_scoped(biz_client, other_client, domain):
    biz_client.post("/api/domains/", {"name": "mine.com"}, format="json")
    assert other_client.get("/api/audit-logs/").json()["results"] == []
    assert biz_client.get("/api/audit-logs/").json()["count"] >= 1


# ----------------------------------------------------------------------------- RBAC
def test_business_admin_cannot_manage_businesses_or_plans(biz_client, business, plan):
    assert (
        biz_client.post(
            "/api/businesses/", {"name": "N", "contact_email": "a@b.c", "plan": plan.pk}, format="json"
        ).status_code
        == 403
    )
    assert biz_client.patch(f"/api/businesses/{business.pk}/", {"name": "Renamed"}, format="json").status_code == 403
    assert biz_client.post(f"/api/businesses/{business.pk}/suspend/").status_code == 403
    assert biz_client.post("/api/plans/", {"code": "x", "name": "x"}, format="json").status_code == 403
    assert biz_client.get("/api/monitoring/reputation/").status_code == 403


def test_ops_admin_cannot_change_plans_or_create_staff(ops_client, plan):
    assert ops_client.patch(f"/api/plans/{plan.pk}/", {"name": "Hack"}, format="json").status_code == 403
    resp = ops_client.post("/api/users/", {"email": "new-ops@bthinkx.test", "role": "OPS_ADMIN"}, format="json")
    assert resp.status_code == 403
    assert ops_client.post("/api/monitoring/run/", {"job": "sync"}, format="json").status_code == 403


def test_business_admin_user_management_is_scoped(biz_client, business, other_business, other_admin):
    resp = biz_client.post(
        "/api/users/",
        {"email": "second@abctraders.com", "role": "SUPER_ADMIN", "business": other_business.pk},
        format="json",
    )
    assert resp.status_code == 403
    resp = biz_client.post(
        "/api/users/", {"email": "second@abctraders.com", "business": other_business.pk}, format="json"
    )
    assert resp.status_code == 201
    assert "temporary_password" in resp.json()
    created = User.objects.get(email="second@abctraders.com")
    assert created.business_id == business.pk and created.must_change_password
    assert biz_client.delete(f"/api/users/{other_admin.pk}/").status_code == 404
    emails = [u["email"] for u in biz_client.get("/api/users/").json()["results"]]
    assert "admin@xyz.com" not in emails


def test_business_admin_cannot_restore_outbound_or_set_limits(biz_client, business, domain, mailcow):
    mb = Mailbox.objects.create(
        business=business,
        domain=domain,
        local_part="s",
        email="s@abctraders.com",
        quota_mb=10,
        status="ACTIVE",
        outbound_suspended=True,
    )
    mailcow.mailboxes["s@abctraders.com"] = {"username": "s@abctraders.com", "attributes": {}}
    assert biz_client.post(f"/api/mailboxes/{mb.pk}/restore-outbound/").status_code == 403
    resp = biz_client.patch(f"/api/mailboxes/{mb.pk}/", {"outbound_limit_per_hour": 9999}, format="json")
    assert resp.status_code == 403


def test_cannot_delete_self_or_last_super_admin(staff_client, super_admin):
    assert staff_client.delete(f"/api/users/{super_admin.pk}/").status_code == 403


def test_super_admin_can_create_ops_admin(staff_client):
    resp = staff_client.post("/api/users/", {"email": "ops2@bthinkx.test", "role": "OPS_ADMIN"}, format="json")
    assert resp.status_code == 201
    assert User.objects.get(email="ops2@bthinkx.test").role == Role.OPS_ADMIN


def test_unauthenticated_is_rejected(db, client):
    for url in ("/api/domains/", "/api/mailboxes/", "/api/dashboard/", "/api/users/"):
        assert client.get(url).status_code == 403


def test_retired_plan_rules(staff_client, business, plan):
    from apps.businesses.models import Plan

    plan.is_active = False
    plan.save()
    # editing a business that stays on its retired plan still works
    resp = staff_client.patch(
        f"/api/businesses/{business.pk}/", {"name": "ABC Traders Ltd", "plan": plan.pk}, format="json"
    )
    assert resp.status_code == 200
    # but a new business cannot be put on it
    resp = staff_client.post(
        "/api/businesses/", {"name": "New", "contact_email": "a@new.com", "plan": plan.pk}, format="json"
    )
    assert resp.status_code == 400
    assert Plan.objects.count() == 1
