from django.conf import settings
from rest_framework import serializers

from .models import Alias, Mailbox


class MailboxSerializer(serializers.ModelSerializer):
    business_name = serializers.CharField(source="business.name", read_only=True)
    domain_name = serializers.CharField(source="domain.name", read_only=True)
    usage_percent = serializers.SerializerMethodField()
    effective_limit_per_hour = serializers.IntegerField(source="effective_hourly_limit", read_only=True)
    effective_limit_per_day = serializers.IntegerField(source="effective_daily_limit", read_only=True)
    webmail_url = serializers.SerializerMethodField()

    class Meta:
        model = Mailbox
        fields = [
            "id",
            "business",
            "business_name",
            "domain",
            "domain_name",
            "local_part",
            "email",
            "display_name",
            "status",
            "quota_mb",
            "used_bytes",
            "message_count",
            "usage_percent",
            "outbound_suspended",
            "outbound_suspended_reason",
            "outbound_suspended_at",
            "outbound_limit_per_hour",
            "outbound_limit_per_day",
            "effective_limit_per_hour",
            "effective_limit_per_day",
            "last_login_at",
            "last_synced_at",
            "last_error",
            "webmail_url",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_usage_percent(self, obj):
        if not obj.quota_mb:
            return 0
        return round(min(obj.used_bytes / obj.quota_bytes * 100, 100), 1)

    def get_webmail_url(self, obj):
        return settings.WEBMAIL_URL


class MailboxCreateSerializer(serializers.Serializer):
    domain = serializers.IntegerField(required=False)
    local_part = serializers.CharField(max_length=64)
    display_name = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    quota_mb = serializers.IntegerField(min_value=1, max_value=10_000_000, required=False)


class MailboxUpdateSerializer(serializers.Serializer):
    display_name = serializers.CharField(max_length=200, required=False, allow_blank=True)
    quota_mb = serializers.IntegerField(min_value=1, max_value=10_000_000, required=False)
    outbound_limit_per_hour = serializers.IntegerField(min_value=1, max_value=100_000, required=False, allow_null=True)
    outbound_limit_per_day = serializers.IntegerField(min_value=1, max_value=1_000_000, required=False, allow_null=True)

    def validate(self, attrs):
        h, d = attrs.get("outbound_limit_per_hour"), attrs.get("outbound_limit_per_day")
        if h and d and h > d:
            raise serializers.ValidationError({"outbound_limit_per_hour": "Hourly limit cannot exceed daily limit."})
        return attrs


class ReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class AliasSerializer(serializers.ModelSerializer):
    business_name = serializers.CharField(source="business.name", read_only=True)
    domain_name = serializers.CharField(source="domain.name", read_only=True)

    class Meta:
        model = Alias
        fields = [
            "id",
            "business",
            "business_name",
            "domain",
            "domain_name",
            "source_address",
            "destinations",
            "status",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class AliasCreateSerializer(serializers.Serializer):
    domain = serializers.IntegerField(required=False)
    local_part = serializers.CharField(max_length=64)
    destinations = serializers.ListField(child=serializers.CharField(max_length=320), min_length=1, max_length=50)


class AliasUpdateSerializer(serializers.Serializer):
    destinations = serializers.ListField(
        child=serializers.CharField(max_length=320), min_length=1, max_length=50, required=False
    )
    status = serializers.ChoiceField(choices=Alias.Status.choices, required=False)
