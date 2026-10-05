"""Translate Mailcow integration errors into API errors for request/response code."""

import logging

from apps.core.exceptions import Conflict, UpstreamError

from .exceptions import MailcowAPIError, MailcowAuthError, MailcowError, MailcowNotConfigured

logger = logging.getLogger(__name__)


def to_api_error(exc: MailcowError, *, conflict_message: str | None = None):
    if (
        isinstance(exc, MailcowAPIError)
        and conflict_message
        and exc.has_code("object_exists", "mailbox_exists", "is_alias_or_mailbox", "is_alias", "domain_exists")
    ):
        return Conflict(conflict_message)
    if isinstance(exc, MailcowAuthError | MailcowNotConfigured):
        from apps.notifications.service import raise_alert

        raise_alert(
            "mailcow-auth",
            "Mailcow API authentication/configuration failure",
            f"The control plane cannot authenticate to Mailcow: {exc.message}",
            severity="CRITICAL",
        )
        return UpstreamError("The mail server is temporarily unavailable. The operations team has been alerted.")
    if isinstance(exc, MailcowAPIError):
        logger.warning("Mailcow refused operation: %s (codes=%s)", exc.message, exc.codes)
        return UpstreamError(f"The mail server refused the operation: {exc.message}")
    return UpstreamError()


CONFLICT_CODES = ("object_exists", "mailbox_exists", "is_alias_or_mailbox", "is_alias", "domain_exists")


def raise_conflict_or_reraise(exc: MailcowError, conflict_message: str):
    """
    Inside a transaction: turn "already exists" into a 409, re-raise anything else
    unchanged so the API exception handler maps it *after* the rollback (alerts
    raised there are not lost with the rolled-back savepoint).
    """
    if isinstance(exc, MailcowAPIError) and exc.has_code(*CONFLICT_CODES):
        raise Conflict(conflict_message) from exc
    raise exc
