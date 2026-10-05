import hmac

from django.conf import settings
from django.utils import timezone
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsPlatformStaff, IsSuperAdmin
from apps.accounts.throttles import LoginThrottle
from apps.audit import service as audit
from apps.notifications.models import Alert

from . import services


class ReputationView(APIView):
    permission_classes = [IsPlatformStaff]

    def get(self, request):
        return Response(services.reputation_summary())


class RunChecksView(APIView):
    """Queue the periodic jobs immediately (super admin)."""

    permission_classes = [IsSuperAdmin]

    JOBS = {
        "health": "apps.monitoring.tasks.check_mailcow_health",
        "blacklists": "apps.monitoring.tasks.check_blacklists",
        "sync": "apps.mailboxes.tasks.sync_mailcow",
        "abuse": "apps.security.tasks.detect_abuse",
        "dns": "apps.domains.tasks.check_all_dns_records",
    }

    def post(self, request):
        from config.celery import app

        job = request.data.get("job")
        if job not in self.JOBS:
            return Response(
                {"detail": f"job must be one of {sorted(self.JOBS)}", "code": "invalid"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        app.send_task(self.JOBS[job])
        audit.record("system.job_triggered", request=request, metadata={"job": job})
        return Response({"queued": job}, status=status.HTTP_202_ACCEPTED)


class BackupReportSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["success", "failure"])
    message = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")
    details = serializers.DictField(required=False, default=dict)


class BackupReportView(APIView):
    """
    Called by the backup script on the mail server:
      curl -H "Authorization: Bearer $BACKUP_REPORT_TOKEN" -d '{"status":"success"}' …
    Disabled (404) unless BACKUP_REPORT_TOKEN is set.
    """

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [LoginThrottle]

    def post(self, request):
        token = settings.BACKUP_REPORT_TOKEN
        if not token:
            return Response(status=status.HTTP_404_NOT_FOUND)
        header = request.META.get("HTTP_AUTHORIZATION", "")
        supplied = header[7:] if header.startswith("Bearer ") else ""
        if not supplied or not hmac.compare_digest(supplied.encode(), token.encode()):
            return Response({"detail": "Invalid token."}, status=status.HTTP_401_UNAUTHORIZED)
        data = BackupReportSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.record_backup_report(**data.validated_data)
        return Response({"recorded": True})


class AlertSerializer(serializers.ModelSerializer):
    class Meta:
        model = Alert
        fields = [
            "id",
            "key",
            "severity",
            "title",
            "message",
            "business",
            "delivered",
            "delivery_error",
            "created_at",
            "acknowledged_at",
        ]
        read_only_fields = fields


class AlertViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = AlertSerializer
    permission_classes = [IsPlatformStaff]

    def get_queryset(self):
        qs = Alert.objects.all()
        if self.request.query_params.get("open") in ("true", "1"):
            qs = qs.filter(acknowledged_at__isnull=True)
        return qs.order_by("-created_at")

    @action(detail=True, methods=["post"])
    def acknowledge(self, request, pk=None):
        alert = self.get_object()
        if alert.acknowledged_at is None:
            alert.acknowledged_at = timezone.now()
            alert.save(update_fields=["acknowledged_at"])
            audit.record("alert.acknowledged", request=request, obj=alert)
        return Response(AlertSerializer(alert).data)
