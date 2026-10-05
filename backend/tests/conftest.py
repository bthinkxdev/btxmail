import pyotp
import pytest
import responses
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.businesses.models import Business, Plan
from apps.domains import dns_checks
from apps.domains.models import Domain, DomainDNSStatus

from .fake_dns import FakeDNS
from .fake_mailcow import FakeMailcow

PASSWORD = "Sup3r-Secure-Passw0rd!"


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture(autouse=True)
def mailcow():
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        yield FakeMailcow(rsps)


@pytest.fixture(autouse=True)
def fake_dns(monkeypatch, settings):
    fake = FakeDNS()
    monkeypatch.setattr(dns_checks, "_query", fake.query)
    fake.set_ptr("10.113.0.203.in-addr.arpa", settings.MAIL_HOSTNAME)
    fake.set_a(settings.MAIL_HOSTNAME, settings.MAIL_IPV4)
    return fake


@pytest.fixture
def plan(db):
    return Plan.objects.create(
        code="starter",
        name="Starter",
        max_domains=2,
        max_mailboxes=3,
        max_aliases=5,
        default_mailbox_quota_mb=1024,
        max_mailbox_quota_mb=2048,
        total_storage_mb=4096,
        outbound_per_hour=20,
        outbound_per_day=100,
    )


@pytest.fixture
def business(plan):
    return Business.objects.create(name="ABC Traders", contact_email="owner@abctraders.com", plan=plan)


@pytest.fixture
def other_business(plan):
    return Business.objects.create(name="XYZ Corp", contact_email="owner@xyz.com", plan=plan)


def make_user(email, role, business=None, *, two_factor=True):
    user = User.objects.create_user(email=email, password=PASSWORD, role=role, business=business)
    if two_factor:
        user.set_pending_totp_secret(pyotp.random_base32())
        user.activate_pending_totp()
        user.save()
    return user


@pytest.fixture
def super_admin(db):
    user = User.objects.create_superuser(email="root@bthinkx.test", password=PASSWORD)
    user.set_pending_totp_secret(pyotp.random_base32())
    user.activate_pending_totp()
    user.save()
    return user


@pytest.fixture
def ops_admin(db):
    return make_user("ops@bthinkx.test", Role.OPS_ADMIN)


@pytest.fixture
def biz_admin(business):
    return make_user("admin@abctraders.com", Role.BUSINESS_ADMIN, business)


@pytest.fixture
def other_admin(other_business):
    return make_user("admin@xyz.com", Role.BUSINESS_ADMIN, other_business)


def client_for(user):
    client = APIClient()
    client.force_login(user)
    return client


@pytest.fixture
def staff_client(super_admin):
    return client_for(super_admin)


@pytest.fixture
def ops_client(ops_admin):
    return client_for(ops_admin)


@pytest.fixture
def biz_client(biz_admin):
    return client_for(biz_admin)


@pytest.fixture
def other_client(other_admin):
    return client_for(other_admin)


def provisioned_domain(business, name, mailcow, *, active=True):
    """Create a domain already verified + provisioned on the fake Mailcow."""
    domain = Domain.objects.create(
        business=business,
        name=name,
        status=Domain.Status.ACTIVE if active else Domain.Status.DNS_PENDING,
        mailcow_provisioned=True,
        dkim_selector="dkim",
        dkim_public_record="v=DKIM1;k=rsa;p=ABC",
    )
    DomainDNSStatus.objects.create(domain=domain)
    mailcow.domains[name] = {"domain_name": name, "active": "1"}
    return domain


@pytest.fixture
def domain(business, mailcow):
    return provisioned_domain(business, "abctraders.com", mailcow)


@pytest.fixture
def other_domain(other_business, mailcow):
    return provisioned_domain(other_business, "xyz.com", mailcow)


@pytest.fixture(autouse=True)
def _run_on_commit_immediately(monkeypatch):
    """Tests run inside one transaction, so on_commit hooks would never fire."""
    from django.db import transaction

    monkeypatch.setattr(transaction, "on_commit", lambda func, using=None, robust=False: func())
