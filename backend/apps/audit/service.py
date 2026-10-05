import logging

from django.db import transaction

from apps.core.middleware import get_request_id
from apps.core.utils import client_ip

from .models import AuditLog

logger = logging.getLogger("audit")

_SENSITIVE_KEYS = {"password", "password2", "token", "secret", "code", "api_key", "temporary_password"}


def _scrub(value):
    if isinstance(value, dict):
        return {k: ("***" if k.lower() in _SENSITIVE_KEYS else _scrub(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


def record(action, *, actor=None, request=None, business=None, obj=None, metadata=None) -> AuditLog:
    """
    Write an audit entry. Never raises: auditing must not break the operation,
    but failures are logged loudly.
    """
    if actor is None and request is not None and getattr(request, "user", None) is not None:
        if request.user.is_authenticated:
            actor = request.user
    try:
        with transaction.atomic():
            entry = AuditLog.objects.create(
                actor=actor if actor is not None and getattr(actor, "pk", None) else None,
                actor_email=getattr(actor, "email", "") or "",
                actor_role=getattr(actor, "role", "") or "",
                business=business,
                action=action,
                object_type=obj.__class__.__name__ if obj is not None else "",
                object_id=str(getattr(obj, "pk", "") or "") if obj is not None else "",
                object_repr=str(obj)[:320] if obj is not None else "",
                ip_address=client_ip(request) if request is not None else None,
                user_agent=(request.META.get("HTTP_USER_AGENT", "")[:255] if request is not None else ""),
                request_id=get_request_id() if get_request_id() != "-" else "",
                metadata=_scrub(metadata or {}),
            )
        logger.info("audit action=%s actor=%s object=%s", action, entry.actor_email or "system", entry.object_repr)
        return entry
    except Exception:  # noqa: BLE001
        logger.exception("Failed to write audit log for action %s", action)
        return AuditLog(action=action)
