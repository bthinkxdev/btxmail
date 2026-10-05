from django.db.models import Sum
from rest_framework import serializers

from .models import Business, Plan


class PlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = Plan
        fields = [
            "id",
            "code",
            "name",
            "description",
            "max_domains",
            "max_mailboxes",
            "max_aliases",
            "default_mailbox_quota_mb",
            "max_mailbox_quota_mb",
            "total_storage_mb",
            "outbound_per_hour",
            "outbound_per_day",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate(self, attrs):
        get = lambda k: attrs.get(k, getattr(self.instance, k, None))  # noqa: E731
        if (
            get("default_mailbox_quota_mb")
            and get("max_mailbox_quota_mb")
            and get("default_mailbox_quota_mb") > get("max_mailbox_quota_mb")
        ):
            raise serializers.ValidationError({"default_mailbox_quota_mb": "Cannot exceed the per-mailbox maximum."})
        if (
            get("max_mailbox_quota_mb")
            and get("total_storage_mb")
            and get("max_mailbox_quota_mb") > get("total_storage_mb")
        ):
            raise serializers.ValidationError({"max_mailbox_quota_mb": "Cannot exceed total storage."})
        if get("outbound_per_hour") and get("outbound_per_day") and get("outbound_per_hour") > get("outbound_per_day"):
            raise serializers.ValidationError({"outbound_per_hour": "Hourly limit cannot exceed the daily limit."})
        return attrs


class BusinessSerializer(serializers.ModelSerializer):
    plan_detail = PlanSerializer(source="plan", read_only=True)
    plan = serializers.PrimaryKeyRelatedField(queryset=Plan.objects.all())
    usage = serializers.SerializerMethodField()

    class Meta:
        model = Business
        fields = [
            "id",
            "name",
            "legal_name",
            "status",
            "contact_person",
            "contact_email",
            "contact_phone",
            "plan",
            "plan_detail",
            "notes",
            "suspended_reason",
            "usage",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "status", "suspended_reason", "usage", "created_at", "updated_at"]

    def validate_plan(self, plan):
        # A retired plan may stay on existing businesses but cannot be newly assigned.
        if not plan.is_active and (self.instance is None or self.instance.plan_id != plan.pk):
            raise serializers.ValidationError("This plan is retired and cannot be assigned.")
        return plan

    def validate_name(self, value):
        value = value.strip()
        qs = Business.objects.filter(name__iexact=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("A business with this name already exists.")
        return value

    def get_usage(self, obj):
        mailboxes = obj.mailboxes.exclude(status="DELETING")
        agg = mailboxes.aggregate(alloc=Sum("quota_mb"), used=Sum("used_bytes"))
        return {
            "domains": obj.domains.count(),
            "mailboxes": mailboxes.count(),
            "aliases": obj.aliases.count(),
            "allocated_storage_mb": agg["alloc"] or 0,
            "used_storage_bytes": agg["used"] or 0,
        }


class BusinessStatusSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
