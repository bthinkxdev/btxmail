"""
Symmetric encryption for small secrets stored in the database (TOTP seeds).

The key comes from FIELD_ENCRYPTION_KEY (a urlsafe base64 32-byte Fernet key).
In DEBUG it falls back to a key derived from SECRET_KEY so local setup works.
"""

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    key = getattr(settings, "FIELD_ENCRYPTION_KEY", "") or ""
    if not key:
        if not settings.DEBUG:
            raise ImproperlyConfigured("FIELD_ENCRYPTION_KEY is required in production.")
        key = base64.urlsafe_b64encode(hashlib.sha256(settings.SECRET_KEY.encode()).digest()).decode()
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except (ValueError, TypeError) as exc:
        raise ImproperlyConfigured("FIELD_ENCRYPTION_KEY is not a valid Fernet key.") from exc


def encrypt(value: str) -> str:
    if not value:
        return ""
    return _fernet().encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise ImproperlyConfigured("Unable to decrypt a stored secret; FIELD_ENCRYPTION_KEY changed?") from exc
