"""Settings for the automated test suite (SQLite, eager Celery, local cache)."""

import os

os.environ.setdefault("DJANGO_DEBUG", "1")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("USE_LOCMEM_CACHE", "1")
os.environ.setdefault("MAILCOW_API_URL", "https://mailcow.test")
os.environ.setdefault("MAILCOW_API_KEY", "test-api-key")
os.environ.setdefault("MAIL_HOSTNAME", "mail.bthinkx.test")
os.environ.setdefault("MAIL_IPV4", "203.0.113.10")
os.environ.setdefault("CELERY_TASK_ALWAYS_EAGER", "1")
os.environ.setdefault("ALERT_EMAILS", "ops@bthinkx.test")
os.environ.setdefault("BACKUP_REPORT_TOKEN", "backup-token-123")
os.environ.setdefault("FIELD_ENCRYPTION_KEY", "3VJ02VgGPGC0IXyHKVvElFcAlPdj0Irs1uuA4AVMGBg=")

from .settings import *  # noqa: E402,F403

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
REST_FRAMEWORK = {
    **REST_FRAMEWORK,
    "DEFAULT_THROTTLE_RATES": {  # noqa: F405
        "anon": "10000/min",
        "user": "10000/min",
        "login": "10000/min",
        "password_reset": "10000/min",
        "sensitive": "10000/min",
    },
}
LOGGING = {"version": 1, "disable_existing_loggers": False, "root": {"level": "CRITICAL"}}
