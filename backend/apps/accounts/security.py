"""Brute-force protection and TOTP helpers for portal logins."""

import hashlib
import io
import time

import pyotp
import qrcode
import qrcode.image.svg
from django.conf import settings
from django.core.cache import cache


def _key(kind: str, value: str) -> str:
    digest = hashlib.sha256(value.lower().encode()).hexdigest()[:32]
    return f"login:{kind}:{digest}"


def is_locked(email: str, ip: str | None) -> bool:
    if cache.get(_key("lock-email", email)):
        return True
    return bool(ip and cache.get(_key("lock-ip", ip)))


def register_failure(email: str, ip: str | None) -> bool:
    """Count a failure. Returns True if this failure triggered a lockout."""
    locked = False
    window = settings.LOGIN_LOCKOUT_SECONDS
    for kind, value, limit in (
        ("email", email, settings.LOGIN_MAX_FAILURES),
        ("ip", ip, settings.LOGIN_MAX_FAILURES * 4),
    ):
        if not value:
            continue
        key = _key(f"fail-{kind}", value)
        cache.add(key, 0, window)
        try:
            count = cache.incr(key)
        except ValueError:
            cache.set(key, 1, window)
            count = 1
        if count >= limit:
            cache.set(_key(f"lock-{kind}", value), 1, window)
            cache.delete(key)
            locked = True
    return locked


def clear_failures(email: str) -> None:
    cache.delete_many([_key("fail-email", email), _key("lock-email", email)])


# --------------------------------------------------------------------------- #
# TOTP
# --------------------------------------------------------------------------- #
def new_totp_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(secret: str, email: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=settings.TOTP_ISSUER)


def qr_svg(data: str) -> str:
    img = qrcode.make(data, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=2)
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue().decode()


def verify_totp(user_id: int, secret: str, code: str) -> bool:
    """Verify a 6-digit code (±1 step) and reject replays of an already-used step."""
    code = (code or "").strip().replace(" ", "")
    if not secret or not code.isdigit() or len(code) != 6:
        return False
    totp = pyotp.TOTP(secret)
    now = time.time()
    for offset in (0, -1, 1):
        step_time = now + offset * totp.interval
        if totp.verify(code, for_time=step_time, valid_window=0):
            step = int(step_time // totp.interval)
            replay_key = f"totp-used:{user_id}:{step}"
            if not cache.add(replay_key, 1, totp.interval * 3):
                return False
            return True
    return False
