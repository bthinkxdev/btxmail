import ipaddress
import secrets
import string

from django.conf import settings


def client_ip(request) -> str | None:
    """
    Return the client IP. Trust X-Forwarded-For only for the configured number
    of reverse proxies (nginx), taking the right-most untrusted address.
    """
    if request is None:
        return None
    num_proxies = settings.REST_FRAMEWORK.get("NUM_PROXIES") or 0
    remote = request.META.get("REMOTE_ADDR")
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    candidate = remote
    if xff and num_proxies > 0:
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if parts:
            candidate = parts[-min(num_proxies, len(parts))]
    try:
        return str(ipaddress.ip_address(candidate)) if candidate else None
    except ValueError:
        return None


_PW_ALPHABET = string.ascii_letters + string.digits
_PW_SYMBOLS = "!@#%^*-_=+"


def generate_password(length: int = 20) -> str:
    """Strong random password with at least one char of each class."""
    if length < 12:
        raise ValueError("Password length must be at least 12")
    while True:
        chars = [secrets.choice(_PW_ALPHABET + _PW_SYMBOLS) for _ in range(length)]
        pw = "".join(chars)
        if (
            any(c.islower() for c in pw)
            and any(c.isupper() for c in pw)
            and any(c.isdigit() for c in pw)
            and any(c in _PW_SYMBOLS for c in pw)
        ):
            return pw
