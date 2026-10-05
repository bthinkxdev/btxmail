from rest_framework.authentication import SessionAuthentication


class CsrfEnforcedSessionAuthentication(SessionAuthentication):
    """
    Session cookie auth with CSRF enforced on every unsafe method.
    (DRF's SessionAuthentication already enforces CSRF for authenticated
    users; this subclass exists so the policy is explicit and greppable.)
    """
