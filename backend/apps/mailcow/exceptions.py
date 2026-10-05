class MailcowError(Exception):
    """Base class for all Mailcow integration errors."""

    retryable = False

    def __init__(self, message: str, *, status_code: int | None = None, payload=None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.payload = payload


class MailcowUnavailable(MailcowError):
    """Network failure, timeout, or 5xx — safe to retry later."""

    retryable = True


class MailcowAuthError(MailcowError):
    """API key rejected or the caller IP is not allowed by Mailcow."""


class MailcowAPIError(MailcowError):
    """Mailcow understood the request but refused it (type=danger/error)."""

    def __init__(self, message: str, *, codes: list[str] | None = None, **kwargs):
        super().__init__(message, **kwargs)
        self.codes = codes or []

    def has_code(self, *codes: str) -> bool:
        return any(code in self.codes for code in codes)


class MailcowNotConfigured(MailcowError):
    """MAILCOW_API_URL / MAILCOW_API_KEY are missing."""
