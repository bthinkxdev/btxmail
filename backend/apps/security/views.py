from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from apps.accounts.permissions import IsFullyAuthenticated, scope_queryset

from . import services
from .models import SecurityEvent


class SecurityEventSerializer(serializers.ModelSerializer):
    business_name = serializers.CharField(source="business.name", read_only=True, default=None)
    mailbox_email = serializers.CharField(source="mailbox.email", read_only=True, default=None)
    resolved_by_email = serializers.CharField(source="resolved_by.email", read_only=True, default=None)
    is_open = serializers.BooleanField(read_only=True)

    class Meta:
        model = SecurityEvent
        fields = [
            "id",
            "business",
            "business_name",
            "mailbox",
            "mailbox_email",
            "subject",
            "event_type",
            "severity",
            "source_ip",
            "message_count",
            "description",
            "details",
            "action_taken",
            "detected_at",
            "resolved_at",
            "resolved_by_email",
            "resolution_note",
            "is_open",
        ]
        read_only_fields = fields


class ResolveSerializer(serializers.Serializer):
    note = serializers.CharField(max_length=2000, required=False, allow_blank=True, default="")


class SecurityEventViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = SecurityEventSerializer
    permission_classes = [IsFullyAuthenticated]

    def get_queryset(self):
        qs = scope_queryset(
            SecurityEvent.objects.select_related("business", "mailbox", "resolved_by"), self.request.user
        )
        p = self.request.query_params
        if p.get("open") in ("true", "1"):
            qs = qs.filter(resolved_at__isnull=True)
        elif p.get("open") in ("false", "0"):
            qs = qs.filter(resolved_at__isnull=False)
        for field in ("severity", "event_type"):
            if p.get(field):
                qs = qs.filter(**{field: p[field]})
        if p.get("mailbox"):
            qs = qs.filter(mailbox_id=p["mailbox"])
        if p.get("business") and self.request.user.is_platform_staff:
            qs = qs.filter(business_id=p["business"])
        return qs.order_by("-detected_at")

    @action(detail=True, methods=["post"])
    def resolve(self, request, pk=None):
        if not request.user.is_platform_staff:
            raise PermissionDenied("Security events are resolved by BThinkX support.")
        data = ResolveSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        event = services.resolve_event(
            self.get_object(), actor=request.user, request=request, note=data.validated_data["note"]
        )
        return Response(SecurityEventSerializer(event).data)
