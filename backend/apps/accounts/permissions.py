"""
RBAC and tenant isolation.

Rule (README §39): the permitted business is ALWAYS derived from the
authenticated user on the server. A business id coming from the client is
only honoured for platform staff.
"""

from django.conf import settings
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission

from .models import Role


def setup_incomplete_reason(user) -> str | None:
    if user.must_change_password:
        return "password_change_required"
    if settings.ENFORCE_2FA and not user.totp_enabled:
        return "two_factor_setup_required"
    return None


class IsAuthenticatedIncomplete(BasePermission):
    """Logged in, even if password change / 2FA enrolment is still pending."""

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_active)


class IsFullyAuthenticated(BasePermission):
    """Default for the API: logged in, password changed, 2FA enrolled, tenant active."""

    message = "Authentication required."

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated and user.is_active):
            return False
        reason = setup_incomplete_reason(user)
        if reason:
            raise PermissionDenied(detail="Complete your account setup first.", code=reason)
        if user.role == Role.BUSINESS_ADMIN:
            business = user.business
            if business is None or not business.is_active:
                raise PermissionDenied(
                    detail="Your business account is suspended. Contact support.", code="business_suspended"
                )
        return True


class IsPlatformStaff(IsFullyAuthenticated):
    message = "Platform administrators only."

    def has_permission(self, request, view):
        return super().has_permission(request, view) and request.user.is_platform_staff


class IsSuperAdmin(IsFullyAuthenticated):
    message = "Super administrators only."

    def has_permission(self, request, view):
        return super().has_permission(request, view) and request.user.is_super_admin


class StaffWriteOrReadOnly(IsFullyAuthenticated):
    """Anyone fully authenticated may read (scoped); only staff may write."""

    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return True
        return request.user.is_platform_staff


def scope_queryset(queryset, user, field: str = "business"):
    """Restrict a queryset to what the user may see."""
    if not user or not user.is_authenticated:
        return queryset.none()
    if user.is_platform_staff:
        return queryset
    if user.role == Role.BUSINESS_ADMIN and user.business_id:
        return queryset.filter(**{f"{field}_id": user.business_id})
    return queryset.none()
