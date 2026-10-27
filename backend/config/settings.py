"""
BThinkX Email Platform — Django settings.

Every deployment-specific value comes from environment variables (see
`.env.example` at the repository root). Nothing secret lives in source code.
"""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------- #
# Environment helpers
# --------------------------------------------------------------------------- #
def env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return default if value is None or value == "" else value


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ImproperlyConfigured(f"{name} must be an integer, got {value!r}") from exc


def env_list(name: str, default: str = "") -> list[str]:
    raw = env(name, default) or ""
    return [item.strip() for item in raw.split(",") if item.strip()]


# --------------------------------------------------------------------------- #
# Core
# --------------------------------------------------------------------------- #
DEBUG = env_bool("DJANGO_DEBUG", False)

SECRET_KEY = env("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "dev-insecure-secret-key-change-me"  # noqa: S105 - dev only
    else:
        raise ImproperlyConfigured("DJANGO_SECRET_KEY is required when DJANGO_DEBUG is false.")
if not DEBUG and len(SECRET_KEY) < 50:
    raise ImproperlyConfigured("DJANGO_SECRET_KEY must be at least 50 characters in production.")

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1" if DEBUG else "")
if not DEBUG and not ALLOWED_HOSTS:
    raise ImproperlyConfigured("DJANGO_ALLOWED_HOSTS is required in production.")

CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "django_prometheus",
    "apps.core",
    "apps.accounts",
    "apps.audit",
    "apps.businesses",
    "apps.domains",
    "apps.mailboxes",
    "apps.mailcow",
    "apps.security",
    "apps.monitoring",
    "apps.notifications",
]

MIDDLEWARE = [
    "django_prometheus.middleware.PrometheusBeforeMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.core.middleware.RequestIdMiddleware",
    "django_prometheus.middleware.PrometheusAfterMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# --------------------------------------------------------------------------- #
# Database / cache
# --------------------------------------------------------------------------- #
DATABASE_URL = env("DATABASE_URL")
if not DATABASE_URL:
    if DEBUG:
        DATABASE_URL = f"sqlite:///{BASE_DIR / 'db.sqlite3'}"
    else:
        raise ImproperlyConfigured("DATABASE_URL is required in production.")

DATABASES = {
    "default": dj_database_url.parse(
        DATABASE_URL,
        conn_max_age=env_int("DATABASE_CONN_MAX_AGE", 60),
        conn_health_checks=True,
    )
}
DATABASES["default"]["ATOMIC_REQUESTS"] = False

REDIS_URL = env("REDIS_URL", "redis://localhost:6379/0")
CACHE_URL = env("CACHE_URL", "redis://localhost:6379/1")

if env_bool("USE_LOCMEM_CACHE", DEBUG and not env("CACHE_URL")):
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": CACHE_URL,
            "KEY_PREFIX": "btx",
        }
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.User"

# --------------------------------------------------------------------------- #
# Auth / passwords
# --------------------------------------------------------------------------- #
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 12},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
PASSWORD_RESET_TIMEOUT = 60 * 60  # 1 hour

LOGIN_MAX_FAILURES = env_int("LOGIN_MAX_FAILURES", 5)
LOGIN_LOCKOUT_SECONDS = env_int("LOGIN_LOCKOUT_SECONDS", 15 * 60)
ENFORCE_2FA = env_bool("ENFORCE_2FA", True)
TOTP_ISSUER = env("TOTP_ISSUER", "BThinkX Mail")
FIELD_ENCRYPTION_KEY = env("FIELD_ENCRYPTION_KEY", "")
if not DEBUG and not FIELD_ENCRYPTION_KEY:
    raise ImproperlyConfigured("FIELD_ENCRYPTION_KEY is required in production (Fernet key).")

# --------------------------------------------------------------------------- #
# Sessions, cookies and transport security
# --------------------------------------------------------------------------- #
SESSION_ENGINE = "django.contrib.sessions.backends.cached_db"
SESSION_COOKIE_AGE = env_int("SESSION_COOKIE_AGE", 8 * 60 * 60)
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_NAME = "btx_session"
CSRF_COOKIE_NAME = "btx_csrftoken"
CSRF_COOKIE_HTTPONLY = False  # SPA reads it to send X-CSRFToken
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_HEADER_NAME = "HTTP_X_CSRFTOKEN"

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = env_bool("USE_X_FORWARDED_HOST", False)

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", True)
    SECURE_REDIRECT_EXEMPT = [r"^healthz$", r"^readyz$", r"^metrics$"]
    SECURE_HSTS_SECONDS = env_int("SECURE_HSTS_SECONDS", 31536000)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", True)
    SECURE_HSTS_PRELOAD = env_bool("SECURE_HSTS_PRELOAD", False)
    if not SECURE_HSTS_PRELOAD:
        # Preload-list submission is hard to undo, so it is an explicit opt-in.
        SILENCED_SYSTEM_CHECKS = ["security.W021"]

# The SPA is served from the same origin as the API; CORS stays closed unless
# an explicit allow-list is configured.
CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS")
CORS_ALLOW_CREDENTIALS = bool(CORS_ALLOWED_ORIGINS)
CORS_URLS_REGEX = r"^/api/.*$"

# --------------------------------------------------------------------------- #
# I18N / static
# --------------------------------------------------------------------------- #
LANGUAGE_CODE = "en-us"
TIME_ZONE = env("TIME_ZONE", "Asia/Kolkata")
USE_I18N = True
USE_TZ = True

STATIC_URL = "/django-static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        )
    },
}

# --------------------------------------------------------------------------- #
# Django REST Framework
# --------------------------------------------------------------------------- #
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["apps.accounts.authentication.CsrfEnforcedSessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["apps.accounts.permissions.IsFullyAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_PAGINATION_CLASS": "apps.core.pagination.StandardPagination",
    "PAGE_SIZE": 25,
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": env("THROTTLE_ANON", "60/min"),
        "user": env("THROTTLE_USER", "600/min"),
        "login": env("THROTTLE_LOGIN", "10/min"),
        "password_reset": env("THROTTLE_PASSWORD_RESET", "5/hour"),
        "sensitive": env("THROTTLE_SENSITIVE", "30/min"),
    },
    "EXCEPTION_HANDLER": "apps.core.exceptions.api_exception_handler",
    "UNAUTHENTICATED_USER": "django.contrib.auth.models.AnonymousUser",
    "NUM_PROXIES": env_int("NUM_PROXIES", 1),
}

# --------------------------------------------------------------------------- #
# Email (transactional / alerts — NOT the Mailcow corporate IP, see README §28)
# --------------------------------------------------------------------------- #
EMAIL_BACKEND = env(
    "EMAIL_BACKEND",
    "django.core.mail.backends.console.EmailBackend" if DEBUG else "django.core.mail.backends.smtp.EmailBackend",
)
EMAIL_HOST = env("EMAIL_HOST", "localhost")
EMAIL_PORT = env_int("EMAIL_PORT", 587)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
EMAIL_USE_SSL = env_bool("EMAIL_USE_SSL", False)
EMAIL_TIMEOUT = env_int("EMAIL_TIMEOUT", 15)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", "BThinkX Mail <no-reply@bthinkx.com>")
SERVER_EMAIL = DEFAULT_FROM_EMAIL

# --------------------------------------------------------------------------- #
# Platform configuration
# --------------------------------------------------------------------------- #
PLATFORM_NAME = env("PLATFORM_NAME", "BThinkX Mail")
PORTAL_URL = (env("PORTAL_URL", "https://portal.bthinkx.com") or "").rstrip("/")
WEBMAIL_URL = (env("WEBMAIL_URL", "https://mail.bthinkx.com/SOGo") or "").rstrip("/")

MAIL_HOSTNAME = (env("MAIL_HOSTNAME", "mail.bthinkx.com") or "").rstrip(".").lower()
MAIL_IPV4 = env("MAIL_IPV4", "")
MAIL_IPV6 = env("MAIL_IPV6", "")

MAILCOW_API_URL = (env("MAILCOW_API_URL", f"https://{MAIL_HOSTNAME}") or "").rstrip("/")
MAILCOW_API_KEY = env("MAILCOW_API_KEY", "")
MAILCOW_VERIFY_TLS = env_bool("MAILCOW_VERIFY_TLS", True)
MAILCOW_TIMEOUT = env_int("MAILCOW_TIMEOUT", 20)

DOMAIN_VERIFICATION_PREFIX = env("DOMAIN_VERIFICATION_PREFIX", "_bthinkx-verification")
DOMAIN_VERIFICATION_TOKEN_PREFIX = env("DOMAIN_VERIFICATION_TOKEN_PREFIX", "btx_verify_")
DOMAIN_VERIFICATION_EXPIRY_DAYS = env_int("DOMAIN_VERIFICATION_EXPIRY_DAYS", 14)
DKIM_SELECTOR = env("DKIM_SELECTOR", "dkim")
DKIM_KEY_SIZE = env_int("DKIM_KEY_SIZE", 2048)
SPF_RECORD = env("SPF_RECORD", "v=spf1 mx -all")
DMARC_RECORD = env("DMARC_RECORD", "v=DMARC1; p=quarantine; adkim=s; aspf=s; pct=100")
DNS_RESOLVERS = env_list("DNS_RESOLVERS", "1.1.1.1,8.8.8.8")
DNS_TIMEOUT = float(env("DNS_TIMEOUT", "5"))
DNSBL_ZONES = env_list(
    "DNSBL_ZONES",
    "zen.spamhaus.org,bl.spamcop.net,b.barracudacentral.org,dnsbl.sorbs.net,psbl.surriel.com",
)
DNSBL_RESOLVERS = env_list("DNSBL_RESOLVERS", "")

# Abuse / outbound protection defaults (per mailbox, overridable per plan)
ABUSE_AUTO_SUSPEND = env_bool("ABUSE_AUTO_SUSPEND", True)
ABUSE_HOURLY_MULTIPLIER = float(env("ABUSE_HOURLY_MULTIPLIER", "3"))
ABUSE_SPAM_THRESHOLD = env_int("ABUSE_SPAM_THRESHOLD", 10)
ABUSE_AUTH_FAILURE_THRESHOLD = env_int("ABUSE_AUTH_FAILURE_THRESHOLD", 20)
ABUSE_LOG_LOOKBACK = env_int("ABUSE_LOG_LOOKBACK", 2000)

DISK_ALERT_PERCENT = env_int("DISK_ALERT_PERCENT", 80)
MAIL_QUEUE_ALERT = env_int("MAIL_QUEUE_ALERT", 200)
TLS_EXPIRY_ALERT_DAYS = env_int("TLS_EXPIRY_ALERT_DAYS", 14)
BACKUP_REPORT_TOKEN = env("BACKUP_REPORT_TOKEN", "")
ALERT_EMAILS = env_list("ALERT_EMAILS")
ALERT_WEBHOOK_URL = env("ALERT_WEBHOOK_URL", "")
ALERT_DEDUP_SECONDS = env_int("ALERT_DEDUP_SECONDS", 60 * 60)

# Web Push (generate keys with `python manage.py generate_vapid_keys`)
VAPID_PUBLIC_KEY = env("VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE_KEY = env("VAPID_PRIVATE_KEY", "")
VAPID_SUBJECT = env("VAPID_SUBJECT", f"mailto:{(ALERT_EMAILS or ['admin@bthinkx.com'])[0]}")
if bool(VAPID_PUBLIC_KEY) != bool(VAPID_PRIVATE_KEY):
    raise ImproperlyConfigured("Set both VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY, or neither.")
PUSH_ENDPOINT_ALLOWED_SUFFIXES = env_list(
    "PUSH_ENDPOINT_ALLOWED_SUFFIXES",
    "fcm.googleapis.com,android.googleapis.com,push.services.mozilla.com,push.apple.com,notify.windows.com",
)
PUSH_TTL_SECONDS = env_int("PUSH_TTL_SECONDS", 24 * 60 * 60)
PUSH_MAIL_RATE_PER_MINUTE = env_int("PUSH_MAIL_RATE_PER_MINUTE", 30)
# Shared secret the mail server presents when a message is delivered (see deploy/mailcow/README.md).
NEW_MAIL_WEBHOOK_TOKEN = env("NEW_MAIL_WEBHOOK_TOKEN", "")
if NEW_MAIL_WEBHOOK_TOKEN and len(NEW_MAIL_WEBHOOK_TOKEN) < 32:
    raise ImproperlyConfigured("NEW_MAIL_WEBHOOK_TOKEN must be at least 32 characters.")

# Django admin is break-glass only (no 2FA). Disabled unless ADMIN_URL is set.
ADMIN_URL = env("ADMIN_URL", "") or ""
if ADMIN_URL and not ADMIN_URL.endswith("/"):
    ADMIN_URL += "/"

METRICS_ALLOWED_IPS = env_list("METRICS_ALLOWED_IPS", "127.0.0.1")

# --------------------------------------------------------------------------- #
# Celery
# --------------------------------------------------------------------------- #
CELERY_BROKER_URL = env("CELERY_BROKER_URL", REDIS_URL)
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", None)
CELERY_TASK_ALWAYS_EAGER = env_bool("CELERY_TASK_ALWAYS_EAGER", False)
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_TIME_LIMIT = 300
CELERY_TASK_SOFT_TIME_LIMIT = 240
CELERY_TASK_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TIMEZONE = TIME_ZONE
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_TASK_DEFAULT_QUEUE = "default"

CELERY_BEAT_SCHEDULE = {
    "verify-pending-domains": {
        "task": "apps.domains.tasks.verify_pending_domains",
        "schedule": timedelta(minutes=env_int("SCHEDULE_VERIFY_MINUTES", 5)),
    },
    "check-dns-records": {
        "task": "apps.domains.tasks.check_all_dns_records",
        "schedule": timedelta(minutes=env_int("SCHEDULE_DNS_MINUTES", 30)),
    },
    "retry-failed-provisioning": {
        "task": "apps.domains.tasks.retry_failed_provisioning",
        "schedule": timedelta(minutes=15),
    },
    "sync-mailcow": {
        "task": "apps.mailboxes.tasks.sync_mailcow",
        "schedule": timedelta(minutes=env_int("SCHEDULE_SYNC_MINUTES", 5)),
    },
    "detect-abuse": {
        "task": "apps.security.tasks.detect_abuse",
        "schedule": timedelta(minutes=env_int("SCHEDULE_ABUSE_MINUTES", 5)),
    },
    "check-blacklists": {
        "task": "apps.monitoring.tasks.check_blacklists",
        "schedule": timedelta(hours=1),
    },
    "check-mailcow-health": {
        "task": "apps.monitoring.tasks.check_mailcow_health",
        "schedule": timedelta(minutes=5),
    },
    "check-backup-freshness": {
        "task": "apps.monitoring.tasks.check_backup_freshness",
        "schedule": timedelta(hours=6),
    },
    "prune-old-records": {
        "task": "apps.monitoring.tasks.prune_old_records",
        "schedule": timedelta(days=1),
    },
}

BACKUP_MAX_AGE_HOURS = env_int("BACKUP_MAX_AGE_HOURS", 26)
AUDIT_RETENTION_DAYS = env_int("AUDIT_RETENTION_DAYS", 730)
HEALTH_RETENTION_DAYS = env_int("HEALTH_RETENTION_DAYS", 30)

# --------------------------------------------------------------------------- #
# Logging (stdout, consumed by Docker → Loki)
# --------------------------------------------------------------------------- #
LOG_LEVEL = env("LOG_LEVEL", "INFO")
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"request_id": {"()": "apps.core.middleware.RequestIdLogFilter"}},
    "formatters": {
        "standard": {
            "format": "%(asctime)s %(levelname)s %(name)s [req=%(request_id)s] %(message)s",
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
            "filters": ["request_id"],
        }
    },
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {
        "django.security": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "django.db.backends": {"handlers": ["console"], "level": "WARNING", "propagate": False},
    },
}

PROMETHEUS_EXPORT_MIGRATIONS = False
