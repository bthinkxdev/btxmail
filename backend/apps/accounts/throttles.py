from rest_framework.throttling import AnonRateThrottle, SimpleRateThrottle, UserRateThrottle


class LoginThrottle(AnonRateThrottle):
    scope = "login"


class PasswordResetThrottle(AnonRateThrottle):
    scope = "password_reset"


class SensitiveActionThrottle(UserRateThrottle):
    """Applied to password resets, mailbox creation and other abuse-prone actions."""

    scope = "sensitive"


class OtpThrottle(SimpleRateThrottle):
    scope = "login"

    def get_cache_key(self, request, view):
        pending = request.session.get("pre_2fa_user_id") if hasattr(request, "session") else None
        ident = pending or self.get_ident(request)
        return self.cache_format % {"scope": "otp", "ident": ident}
