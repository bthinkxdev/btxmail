import logging
import time

from django.conf import settings
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit import service as audit
from apps.businesses.models import Business
from apps.core.utils import client_ip, generate_password
from apps.security.models import SecurityEvent
from apps.security.services import record_event

from . import security
from .models import Role, User
from .permissions import IsAuthenticatedIncomplete, IsFullyAuthenticated, scope_queryset
from .serializers import (
    LoginSerializer,
    MeSerializer,
    OtpSerializer,
    PasswordChangeSerializer,
    PasswordConfirmSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    UserCreateSerializer,
    UserSerializer,
    UserUpdateSerializer,
)
from .throttles import LoginThrottle, OtpThrottle, PasswordResetThrottle, SensitiveActionThrottle

logger = logging.getLogger(__name__)

PENDING_2FA_KEY = "pre_2fa_user_id"
PENDING_2FA_AT = "pre_2fa_at"
PENDING_2FA_TTL = 300
INVALID_CREDENTIALS = "Invalid e-mail or password."
LOCKED_OUT = "Too many failed attempts. Try again later or reset your password."


def _me(user, request):
    return MeSerializer(user, context={"request": request}).data


@method_decorator(ensure_csrf_cookie, name="get")
class CsrfView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"detail": "ok"})


@method_decorator(csrf_protect, name="post")
class LoginView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [LoginThrottle]

    def post(self, request):
        data = LoginSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        email = data.validated_data["email"].strip().lower()
        ip = client_ip(request)

        if security.is_locked(email, ip):
            audit.record("auth.login_blocked", request=request, metadata={"email": email})
            return Response({"detail": LOCKED_OUT, "code": "locked"}, status=status.HTTP_429_TOO_MANY_REQUESTS)

        user = authenticate(request, email=email, password=data.validated_data["password"])
        if user is None:
            if security.register_failure(email, ip):
                target = User.objects.filter(email__iexact=email).first()
                record_event(
                    event_type=SecurityEvent.EventType.PORTAL_LOCKOUT,
                    severity=SecurityEvent.Severity.MEDIUM,
                    subject=email,
                    business=target.business if target else None,
                    source_ip=ip,
                    description="Portal login locked after repeated failures.",
                )
            audit.record("auth.login_failed", request=request, metadata={"email": email})
            return Response(
                {"detail": INVALID_CREDENTIALS, "code": "invalid_credentials"}, status=status.HTTP_400_BAD_REQUEST
            )

        security.clear_failures(email)
        if user.totp_enabled:
            request.session.cycle_key()
            request.session[PENDING_2FA_KEY] = user.pk
            request.session[PENDING_2FA_AT] = int(time.time())
            return Response({"status": "otp_required"})

        login(request, user)
        audit.record("auth.login", actor=user, request=request, business=user.business)
        return Response({"status": "ok", "user": _me(user, request)})


@method_decorator(csrf_protect, name="post")
class LoginOtpView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [OtpThrottle]

    def post(self, request):
        data = OtpSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        user_id = request.session.get(PENDING_2FA_KEY)
        started = request.session.get(PENDING_2FA_AT, 0)
        if not user_id or time.time() - started > PENDING_2FA_TTL:
            request.session.pop(PENDING_2FA_KEY, None)
            return Response(
                {"detail": "Your sign-in expired. Start again.", "code": "otp_expired"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        user = User.objects.filter(pk=user_id, is_active=True).first()
        if user is None:
            request.session.flush()
            return Response(
                {"detail": INVALID_CREDENTIALS, "code": "invalid_credentials"}, status=status.HTTP_400_BAD_REQUEST
            )
        ip = client_ip(request)
        if security.is_locked(user.email, ip):
            request.session.flush()
            return Response({"detail": LOCKED_OUT, "code": "locked"}, status=status.HTTP_429_TOO_MANY_REQUESTS)

        code = data.validated_data["code"].strip()
        ok = security.verify_totp(user.pk, user.totp_secret, code)
        used_recovery = False
        if not ok and len(code.replace("-", "")) == 10:
            ok = used_recovery = user.consume_recovery_code(code)
        if not ok:
            security.register_failure(user.email, ip)
            audit.record("auth.otp_failed", actor=user, request=request, business=user.business)
            return Response(
                {
                    "detail": "Invalid or already-used code. Wait for the next code and try again.",
                    "code": "invalid_otp",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        request.session.pop(PENDING_2FA_KEY, None)
        request.session.pop(PENDING_2FA_AT, None)
        security.clear_failures(user.email)
        login(request, user)
        audit.record(
            "auth.login",
            actor=user,
            request=request,
            business=user.business,
            metadata={"method": "recovery_code" if used_recovery else "totp"},
        )
        return Response({"status": "ok", "user": _me(user, request)})


class LogoutView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        if request.user.is_authenticated:
            audit.record("auth.logout", request=request, business=request.user.business)
        logout(request)
        return Response({"status": "ok"})


class MeView(APIView):
    permission_classes = [IsAuthenticatedIncomplete]

    def get(self, request):
        return Response(_me(request.user, request))


class PasswordChangeView(APIView):
    permission_classes = [IsAuthenticatedIncomplete]
    throttle_classes = [SensitiveActionThrottle]

    def post(self, request):
        data = PasswordChangeSerializer(data=request.data, context={"request": request})
        data.is_valid(raise_exception=True)
        user = request.user
        user.set_password(data.validated_data["new_password"])
        user.must_change_password = False
        user.password_changed_at = timezone.now()
        user.save(update_fields=["password", "must_change_password", "password_changed_at"])
        update_session_auth_hash(request, user)
        audit.record("auth.password_changed", request=request, business=user.business, obj=user)
        return Response(_me(user, request))


@method_decorator(csrf_protect, name="post")
class PasswordResetRequestView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [PasswordResetThrottle]

    def post(self, request):
        data = PasswordResetRequestSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        email = data.validated_data["email"].strip().lower()
        user = User.objects.filter(email__iexact=email, is_active=True).first()
        if user is not None:
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)
            link = f"{settings.PORTAL_URL}/reset-password?uid={uid}&token={token}"
            try:
                send_mail(
                    f"{settings.PLATFORM_NAME}: reset your password",
                    f"A password reset was requested for {user.email}.\n\n"
                    f"Open this link within one hour to choose a new password:\n{link}\n\n"
                    "If you did not request this, ignore this e-mail.",
                    settings.DEFAULT_FROM_EMAIL,
                    [user.email],
                )
            except Exception:  # noqa: BLE001 - never reveal delivery problems to the caller
                logger.exception("Password reset e-mail failed for user %s", user.pk)
            audit.record("auth.password_reset_requested", actor=user, request=request, business=user.business)
        # Identical response whether or not the account exists (no enumeration).
        return Response({"detail": "If the account exists, a reset link has been sent."})


@method_decorator(csrf_protect, name="post")
class PasswordResetConfirmView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [PasswordResetThrottle]

    def post(self, request):
        data = PasswordResetConfirmSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        invalid = Response(
            {"detail": "This reset link is invalid or has expired.", "code": "invalid_token"},
            status=status.HTTP_400_BAD_REQUEST,
        )
        try:
            pk = force_str(urlsafe_base64_decode(data.validated_data["uid"]))
            user = User.objects.get(pk=int(pk), is_active=True)
        except (ValueError, TypeError, OverflowError, User.DoesNotExist):
            return invalid
        if not default_token_generator.check_token(user, data.validated_data["token"]):
            return invalid
        try:
            validate_password(data.validated_data["new_password"], user)
        except DjangoValidationError as exc:
            raise ValidationError({"new_password": exc.messages}) from exc
        user.set_password(data.validated_data["new_password"])
        user.must_change_password = False
        user.password_changed_at = timezone.now()
        user.save(update_fields=["password", "must_change_password", "password_changed_at"])
        security.clear_failures(user.email)
        audit.record("auth.password_reset_completed", actor=user, request=request, business=user.business)
        return Response({"detail": "Password updated. You can sign in now."})


# --------------------------------------------------------------------------- #
# Two-factor authentication
# --------------------------------------------------------------------------- #
class TwoFactorSetupView(APIView):
    permission_classes = [IsAuthenticatedIncomplete]

    def post(self, request):
        user = request.user
        if user.totp_enabled:
            raise ValidationError({"detail": "Two-factor authentication is already enabled."})
        secret = security.new_totp_secret()
        user.set_pending_totp_secret(secret)
        user.save(update_fields=["totp_pending_secret_encrypted"])
        uri = security.provisioning_uri(secret, user.email)
        return Response({"secret": secret, "otpauth_uri": uri, "qr_svg": security.qr_svg(uri)})


class TwoFactorEnableView(APIView):
    permission_classes = [IsAuthenticatedIncomplete]
    throttle_classes = [SensitiveActionThrottle]

    def post(self, request):
        data = OtpSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        user = request.user
        if user.totp_enabled:
            raise ValidationError({"detail": "Two-factor authentication is already enabled."})
        secret = user.totp_pending_secret
        if not secret:
            raise ValidationError({"detail": "Start the setup first."})
        if not security.verify_totp(user.pk, secret, data.validated_data["code"]):
            raise ValidationError({"code": "Invalid code. Check your device clock and try again."})
        user.activate_pending_totp()
        codes = user.generate_recovery_codes()
        user.save(
            update_fields=[
                "totp_secret_encrypted",
                "totp_pending_secret_encrypted",
                "totp_enabled",
                "recovery_code_hashes",
            ]
        )
        audit.record("auth.2fa_enabled", request=request, business=user.business, obj=user)
        return Response({"recovery_codes": codes, "user": _me(user, request)})


class TwoFactorDisableView(APIView):
    permission_classes = [IsAuthenticatedIncomplete]
    throttle_classes = [SensitiveActionThrottle]

    def post(self, request):
        if settings.ENFORCE_2FA:
            raise PermissionDenied("Two-factor authentication is mandatory on this platform.")
        data = PasswordConfirmSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        user = request.user
        if not user.check_password(data.validated_data["password"]):
            raise ValidationError({"password": "Password is incorrect."})
        if user.totp_enabled and not security.verify_totp(
            user.pk, user.totp_secret, data.validated_data.get("code", "")
        ):
            raise ValidationError({"code": "Invalid code."})
        user.disable_totp()
        user.save(
            update_fields=[
                "totp_secret_encrypted",
                "totp_pending_secret_encrypted",
                "totp_enabled",
                "recovery_code_hashes",
            ]
        )
        audit.record("auth.2fa_disabled", request=request, business=user.business, obj=user)
        return Response(_me(user, request))


class RecoveryCodesView(APIView):
    permission_classes = [IsFullyAuthenticated]
    throttle_classes = [SensitiveActionThrottle]

    def post(self, request):
        data = PasswordConfirmSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        user = request.user
        if not user.totp_enabled:
            raise ValidationError({"detail": "Enable two-factor authentication first."})
        if not user.check_password(data.validated_data["password"]):
            raise ValidationError({"password": "Password is incorrect."})
        codes = user.generate_recovery_codes()
        user.save(update_fields=["recovery_code_hashes"])
        audit.record("auth.recovery_codes_regenerated", request=request, business=user.business, obj=user)
        return Response({"recovery_codes": codes})


# --------------------------------------------------------------------------- #
# Portal user management
# --------------------------------------------------------------------------- #
def can_manage(actor: User, target: User) -> bool:
    if actor.pk == target.pk:
        return False
    if actor.is_super_admin:
        return True
    if actor.role == Role.OPS_ADMIN:
        return target.role == Role.BUSINESS_ADMIN
    return target.role == Role.BUSINESS_ADMIN and target.business_id == actor.business_id


def _send_invite(user: User, temp_password: str) -> None:
    try:
        send_mail(
            f"Your {settings.PLATFORM_NAME} administrator account",
            f"An account has been created for you on {settings.PLATFORM_NAME}.\n\n"
            f"Sign in at {settings.PORTAL_URL} with {user.email}. Your administrator will share the "
            "temporary password with you separately. You will be asked to change it and enable "
            "two-factor authentication at first sign-in.",
            settings.DEFAULT_FROM_EMAIL,
            [user.email],
        )
    except Exception:  # noqa: BLE001
        logger.exception("Invite e-mail failed for user %s", user.pk)


class UserViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet):
    serializer_class = UserSerializer
    permission_classes = [IsFullyAuthenticated]

    def get_queryset(self):
        qs = scope_queryset(User.objects.select_related("business"), self.request.user)
        params = self.request.query_params
        if params.get("role"):
            qs = qs.filter(role=params["role"])
        if params.get("business") and self.request.user.is_platform_staff:
            qs = qs.filter(business_id=params["business"])
        if params.get("search"):
            qs = qs.filter(email__icontains=params["search"].strip())
        return qs.order_by("email")

    def _target(self) -> User:
        target = self.get_object()
        if not can_manage(self.request.user, target):
            raise PermissionDenied("You cannot manage this user.")
        return target

    def create(self, request):
        data = UserCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        actor = request.user
        role = data.validated_data["role"]
        business = None
        if actor.role == Role.BUSINESS_ADMIN:
            if role != Role.BUSINESS_ADMIN:
                raise PermissionDenied("You can only create business administrators.")
            business = actor.business
        else:
            if actor.role == Role.OPS_ADMIN and role != Role.BUSINESS_ADMIN:
                raise PermissionDenied("Only super admins can create platform administrators.")
            if role == Role.BUSINESS_ADMIN:
                business_id = data.validated_data.get("business")
                business = Business.objects.filter(pk=business_id).first() if business_id else None
                if business is None:
                    raise ValidationError({"business": "Select a valid business."})
        temp_password = generate_password()
        with transaction.atomic():
            user = User.objects.create_user(
                email=data.validated_data["email"],
                password=temp_password,
                full_name=data.validated_data.get("full_name", ""),
                role=role,
                business=business,
                is_staff=role == Role.SUPER_ADMIN,
                is_superuser=role == Role.SUPER_ADMIN,
                must_change_password=True,
            )
            audit.record("user.created", request=request, business=business, obj=user, metadata={"role": role})
        _send_invite(user, temp_password)
        payload = UserSerializer(user).data
        payload["temporary_password"] = temp_password
        return Response(payload, status=status.HTTP_201_CREATED)

    def partial_update(self, request, pk=None):
        target = self._target()
        data = UserUpdateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        changes = {}
        if "full_name" in data.validated_data:
            target.full_name = data.validated_data["full_name"]
            changes["full_name"] = target.full_name
        if "is_active" in data.validated_data:
            target.is_active = data.validated_data["is_active"]
            changes["is_active"] = target.is_active
        if "role" in data.validated_data and data.validated_data["role"] != target.role:
            if not request.user.is_super_admin:
                raise PermissionDenied("Only super admins can change roles.")
            new_role = data.validated_data["role"]
            if (new_role == Role.BUSINESS_ADMIN) != (target.role == Role.BUSINESS_ADMIN):
                raise ValidationError({"role": "Cannot move users between platform and business roles."})
            target.role = new_role
            target.is_staff = target.is_superuser = new_role == Role.SUPER_ADMIN
            changes["role"] = new_role
        if changes:
            target.full_clean(exclude=["password"])
            target.save()
            audit.record("user.updated", request=request, business=target.business, obj=target, metadata=changes)
        return Response(UserSerializer(target).data)

    def destroy(self, request, pk=None):
        target = self._target()
        if target.is_super_admin and User.objects.filter(role=Role.SUPER_ADMIN, is_active=True).count() <= 1:
            raise ValidationError({"detail": "Cannot delete the last super admin."})
        business, email = target.business, target.email
        target.delete()
        audit.record("user.deleted", request=request, business=business, metadata={"email": email})
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"], url_path="reset-password", throttle_classes=[SensitiveActionThrottle])
    def reset_password(self, request, pk=None):
        target = self._target()
        temp_password = generate_password()
        target.set_password(temp_password)
        target.must_change_password = True
        target.save(update_fields=["password", "must_change_password"])
        security.clear_failures(target.email)
        audit.record("user.password_reset", request=request, business=target.business, obj=target)
        return Response({"temporary_password": temp_password})

    @action(detail=True, methods=["post"], url_path="reset-2fa")
    def reset_2fa(self, request, pk=None):
        if not request.user.is_platform_staff:
            raise NotFound()
        target = self._target()
        target.disable_totp()
        target.save(
            update_fields=[
                "totp_secret_encrypted",
                "totp_pending_secret_encrypted",
                "totp_enabled",
                "recovery_code_hashes",
            ]
        )
        audit.record("user.2fa_reset", request=request, business=target.business, obj=target)
        return Response(UserSerializer(target).data)
