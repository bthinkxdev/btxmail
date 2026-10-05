from rest_framework import mixins, serializers, viewsets

from apps.accounts.permissions import IsFullyAuthenticated, scope_queryset

from .models import AuditLog


class AuditLogSerializer(serializers.ModelSerializer):
    business_name = serializers.CharField(source="business.name", read_only=True, default=None)

    class Meta:
        model = AuditLog
        fields = [
            "id",
            "timestamp",
            "actor_email",
            "actor_role",
            "business",
            "business_name",
            "action",
            "object_type",
            "object_id",
            "object_repr",
            "ip_address",
            "user_agent",
            "request_id",
            "metadata",
        ]
        read_only_fields = fields


class AuditLogViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = AuditLogSerializer
    permission_classes = [IsFullyAuthenticated]

    def get_queryset(self):
        qs = scope_queryset(AuditLog.objects.select_related("business"), self.request.user)
        p = self.request.query_params
        if p.get("action"):
            qs = qs.filter(action__startswith=p["action"])
        if p.get("actor"):
            qs = qs.filter(actor_email__icontains=p["actor"])
        if p.get("object_type"):
            qs = qs.filter(object_type=p["object_type"])
        if p.get("search"):
            qs = qs.filter(object_repr__icontains=p["search"])
        if p.get("business") and self.request.user.is_platform_staff:
            qs = qs.filter(business_id=p["business"])
        return qs.order_by("-timestamp")
