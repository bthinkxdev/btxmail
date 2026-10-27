import hmac

from django.conf import settings
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import scope_queryset
from apps.accounts.throttles import SensitiveActionThrottle
from apps.mailboxes.models import Mailbox

from . import push
from .models import MailWatch, NotificationPreference, PushSubscription
from .tasks import push_new_mail


class PushConfigView(APIView):
    def get(self, request):
        return Response({"enabled": push.push_enabled(), "public_key": settings.VAPID_PUBLIC_KEY})


class SubscriptionSerializer(serializers.Serializer):
    endpoint = serializers.URLField(max_length=700)
    keys = serializers.DictField(child=serializers.CharField(max_length=255))

    def validate_endpoint(self, value):
        if not push.endpoint_allowed(value):
            raise serializers.ValidationError("This push service is not supported.")
        return value

    def validate_keys(self, value):
        if not value.get("p256dh") or not value.get("auth"):
            raise serializers.ValidationError("p256dh and auth are required.")
        return value


class SubscriptionView(APIView):
    throttle_classes = [SensitiveActionThrottle]

    def post(self, request):
        if not push.push_enabled():
            return Response({"detail": "Notifications are not enabled on this server.", "code": "disabled"}, status=503)
        data = SubscriptionSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        # The endpoint is unique per browser profile: re-subscribing (or another user signing in on
        # the same browser) moves it to the current user.
        PushSubscription.objects.update_or_create(
            endpoint=v["endpoint"],
            defaults={
                "user": request.user,
                "p256dh": v["keys"]["p256dh"],
                "auth": v["keys"]["auth"],
                "user_agent": request.META.get("HTTP_USER_AGENT", "")[:300],
                "active": True,
                "failure_count": 0,
            },
        )
        return Response({"subscribed": True}, status=status.HTTP_201_CREATED)

    def delete(self, request):
        endpoint = request.data.get("endpoint", "")
        PushSubscription.objects.filter(user=request.user, endpoint=endpoint).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class PreferencesSerializer(serializers.Serializer):
    new_mail = serializers.BooleanField(required=False)
    security = serializers.BooleanField(required=False)
    domains = serializers.BooleanField(required=False)
    system = serializers.BooleanField(required=False)
    watched_mailboxes = serializers.ListField(child=serializers.IntegerField(), required=False, max_length=200)


def _preferences(user) -> dict:
    pref, _ = NotificationPreference.objects.get_or_create(user=user)
    own = Mailbox.objects.filter(email__iexact=user.email).values_list("pk", flat=True)
    return {
        "new_mail": pref.new_mail,
        "security": pref.security,
        "domains": pref.domains,
        "system": pref.system and user.is_platform_staff,
        "watched_mailboxes": sorted(set(MailWatch.objects.filter(user=user).values_list("mailbox_id", flat=True))),
        "own_mailboxes": sorted(own),
        "devices": PushSubscription.objects.filter(user=user, active=True).count(),
    }


class PreferencesView(APIView):
    def get(self, request):
        return Response(_preferences(request.user))

    def patch(self, request):
        data = PreferencesSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        pref, _ = NotificationPreference.objects.get_or_create(user=request.user)
        for field in ("new_mail", "security", "domains", "system"):
            if field in v:
                setattr(pref, field, v[field])
        pref.save()
        if "watched_mailboxes" in v:
            # Only mailboxes the user may see can be watched (tenant isolation).
            allowed = set(
                scope_queryset(Mailbox.objects.filter(pk__in=v["watched_mailboxes"]), request.user).values_list(
                    "pk", flat=True
                )
            )
            MailWatch.objects.filter(user=request.user).exclude(mailbox_id__in=allowed).delete()
            for pk in allowed:
                MailWatch.objects.get_or_create(user=request.user, mailbox_id=pk)
        return Response(_preferences(request.user))


class TestPushView(APIView):
    throttle_classes = [SensitiveActionThrottle]

    def post(self, request):
        sent = push.notify_users(
            [request.user],
            kind="test",
            preference="system" if request.user.is_platform_staff else "new_mail",
            title="Notifications are on",
            body="You will be notified here about new mail and important account events.",
            url="/account",
            tag="test",
            center=getattr(request.user.business, "name", "") if request.user.business_id else "",
            account=request.user.email,
        )
        if not sent:
            return Response(
                {"detail": "No device is registered for this account.", "code": "no_devices"},
                status=status.HTTP_409_CONFLICT,
            )
        return Response({"sent": sent})


class NewMailHookView(APIView):
    """
    Called by the mail server for every delivered message:
      curl -H "Authorization: Bearer $NEW_MAIL_WEBHOOK_TOKEN" -d '{"recipient":…,"sender":…,"subject":…}'
    Only metadata is sent; message bodies never leave the mail server. Disabled (404) without a token.
    """

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = []

    def post(self, request):
        token = settings.NEW_MAIL_WEBHOOK_TOKEN
        if not token:
            return Response(status=status.HTTP_404_NOT_FOUND)
        header = request.META.get("HTTP_AUTHORIZATION", "")
        supplied = header[7:] if header.startswith("Bearer ") else ""
        if not supplied or not hmac.compare_digest(supplied.encode(), token.encode()):
            return Response({"detail": "Invalid token."}, status=status.HTTP_401_UNAUTHORIZED)
        body = request.data if isinstance(request.data, dict) else {}

        def field(*names, limit):
            for name in names:
                value = body.get(name)
                if isinstance(value, str) and value:
                    return value[:limit]
            return ""

        recipient = field("recipient", "user", limit=320)  # "user" is Dovecot's push-notification format
        if recipient:
            push_new_mail.delay(recipient, field("sender", "from", limit=1000), field("subject", limit=2000))
        return Response({"accepted": True}, status=status.HTTP_202_ACCEPTED)
