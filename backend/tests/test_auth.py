import re

import pyotp
import pytest
from django.core import mail
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.audit.models import AuditLog
from apps.security.models import SecurityEvent

from .conftest import PASSWORD, make_user

pytestmark = pytest.mark.django_db


def csrf_client():
    client = APIClient(enforce_csrf_checks=True)
    client.get("/api/auth/csrf/")
    token = client.cookies["btx_csrftoken"].value
    client.credentials(HTTP_X_CSRFTOKEN=token)
    return client


def refresh_csrf(client):
    client.credentials(HTTP_X_CSRFTOKEN=client.cookies["btx_csrftoken"].value)


def test_login_requires_csrf(biz_admin):
    client = APIClient(enforce_csrf_checks=True)
    resp = client.post("/api/auth/login/", {"email": biz_admin.email, "password": PASSWORD}, format="json")
    assert resp.status_code == 403


def test_login_without_2fa_requires_setup(business):
    user = make_user("new@abctraders.com", Role.BUSINESS_ADMIN, business, two_factor=False)
    client = csrf_client()
    resp = client.post("/api/auth/login/", {"email": user.email, "password": PASSWORD}, format="json")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert resp.json()["user"]["setup_required"] == "two_factor_setup_required"
    refresh_csrf(client)
    # Gate: the rest of the API is closed until 2FA is enrolled
    resp = client.get("/api/domains/")
    assert resp.status_code == 403
    assert resp.json()["code"] == "two_factor_setup_required"

    setup = client.post("/api/auth/2fa/setup/", format="json").json()
    assert setup["qr_svg"].startswith("<?xml") or "<svg" in setup["qr_svg"]
    code = pyotp.TOTP(setup["secret"]).now()
    enabled = client.post("/api/auth/2fa/enable/", {"code": code}, format="json")
    assert enabled.status_code == 200
    assert len(enabled.json()["recovery_codes"]) == 10
    assert client.get("/api/domains/").status_code == 200


def test_full_otp_login_and_replay_protection(biz_admin):
    client = csrf_client()
    resp = client.post("/api/auth/login/", {"email": biz_admin.email, "password": PASSWORD}, format="json")
    assert resp.json() == {"status": "otp_required"}
    # not logged in yet
    assert client.get("/api/auth/me/").status_code == 403

    code = pyotp.TOTP(biz_admin.totp_secret).now()
    resp = client.post("/api/auth/login/otp/", {"code": code}, format="json")
    assert resp.status_code == 200
    refresh_csrf(client)
    assert client.get("/api/auth/me/").json()["email"] == biz_admin.email
    client.post("/api/auth/logout/")

    # Same code cannot be replayed
    client = csrf_client()
    client.post("/api/auth/login/", {"email": biz_admin.email, "password": PASSWORD}, format="json")
    resp = client.post("/api/auth/login/otp/", {"code": code}, format="json")
    assert resp.status_code == 400


def test_recovery_code_login_is_single_use(biz_admin):
    codes = biz_admin.generate_recovery_codes()
    biz_admin.save()
    client = csrf_client()
    client.post("/api/auth/login/", {"email": biz_admin.email, "password": PASSWORD}, format="json")
    assert client.post("/api/auth/login/otp/", {"code": codes[0]}, format="json").status_code == 200
    client = csrf_client()
    client.post("/api/auth/login/", {"email": biz_admin.email, "password": PASSWORD}, format="json")
    assert client.post("/api/auth/login/otp/", {"code": codes[0]}, format="json").status_code == 400


def test_invalid_credentials_and_lockout(biz_admin, settings):
    client = csrf_client()
    for _ in range(settings.LOGIN_MAX_FAILURES):
        resp = client.post("/api/auth/login/", {"email": biz_admin.email, "password": "wrong"}, format="json")
        assert resp.status_code == 400
        assert resp.json()["detail"] == "Invalid e-mail or password."
    # Even the right password is refused while locked
    resp = client.post("/api/auth/login/", {"email": biz_admin.email, "password": PASSWORD}, format="json")
    assert resp.status_code == 429
    assert SecurityEvent.objects.filter(event_type="PORTAL_LOCKOUT", subject=biz_admin.email).exists()


def test_unknown_email_gets_same_error(db):
    client = csrf_client()
    resp = client.post("/api/auth/login/", {"email": "nobody@x.com", "password": "x"}, format="json")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Invalid e-mail or password."


def test_inactive_user_cannot_login(biz_admin):
    biz_admin.is_active = False
    biz_admin.save()
    client = csrf_client()
    resp = client.post("/api/auth/login/", {"email": biz_admin.email, "password": PASSWORD}, format="json")
    assert resp.status_code == 400


def test_must_change_password_gate(biz_admin, biz_client):
    biz_admin.must_change_password = True
    biz_admin.save()
    assert biz_client.get("/api/domains/").json()["code"] == "password_change_required"
    resp = biz_client.post(
        "/api/auth/password/change/", {"current_password": PASSWORD, "new_password": "short"}, format="json"
    )
    assert resp.status_code == 400
    resp = biz_client.post(
        "/api/auth/password/change/",
        {"current_password": PASSWORD, "new_password": "An0ther-Str0ng-Pass!"},
        format="json",
    )
    assert resp.status_code == 200
    assert biz_client.get("/api/domains/").status_code == 200


def test_password_reset_flow_without_enumeration(biz_admin):
    client = csrf_client()
    r1 = client.post("/api/auth/password/reset/", {"email": biz_admin.email}, format="json")
    r2 = client.post("/api/auth/password/reset/", {"email": "ghost@nowhere.com"}, format="json")
    assert r1.status_code == r2.status_code == 200
    assert r1.json() == r2.json()
    assert len(mail.outbox) == 1
    match = re.search(r"uid=([^&\s]+)&token=([^\s]+)", mail.outbox[0].body)
    uid, token = match.group(1), match.group(2)
    resp = client.post(
        "/api/auth/password/reset/confirm/",
        {"uid": uid, "token": token, "new_password": "Brand-New-Passw0rd!"},
        format="json",
    )
    assert resp.status_code == 200
    biz_admin.refresh_from_db()
    assert biz_admin.check_password("Brand-New-Passw0rd!")
    # token is single use
    resp = client.post(
        "/api/auth/password/reset/confirm/",
        {"uid": uid, "token": token, "new_password": "Another-New-Passw0rd!"},
        format="json",
    )
    assert resp.status_code == 400


def test_suspended_business_admin_is_blocked(business, biz_admin, biz_client):
    business.status = "SUSPENDED"
    business.save()
    resp = biz_client.get("/api/domains/")
    assert resp.status_code == 403
    assert resp.json()["code"] == "business_suspended"


def test_totp_secret_encrypted_at_rest(biz_admin):
    raw = User.objects.filter(pk=biz_admin.pk).values_list("totp_secret_encrypted", flat=True).first()
    assert raw and biz_admin.totp_secret not in raw


def test_login_is_audited(biz_admin):
    client = csrf_client()
    client.post("/api/auth/login/", {"email": biz_admin.email, "password": "bad"}, format="json")
    entry = AuditLog.objects.get(action="auth.login_failed")
    assert entry.metadata["email"] == biz_admin.email
    assert "password" not in entry.metadata
