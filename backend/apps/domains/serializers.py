from rest_framework import serializers

from .models import Domain, DomainDNSStatus


class DomainDNSStatusSerializer(serializers.ModelSerializer):
    is_ready = serializers.BooleanField(read_only=True)

    class Meta:
        model = DomainDNSStatus
        fields = [
            "mx_status",
            "spf_status",
            "dkim_status",
            "dmarc_status",
            "ptr_status",
            "details",
            "last_checked",
            "is_ready",
        ]
        read_only_fields = fields


class DomainSerializer(serializers.ModelSerializer):
    business_name = serializers.CharField(source="business.name", read_only=True)
    dns_status = DomainDNSStatusSerializer(read_only=True)
    dns_records = serializers.SerializerMethodField()
    verification = serializers.SerializerMethodField()
    mailbox_count = serializers.IntegerField(source="mailboxes.count", read_only=True)
    alias_count = serializers.IntegerField(source="aliases.count", read_only=True)

    class Meta:
        model = Domain
        fields = [
            "id",
            "business",
            "business_name",
            "name",
            "status",
            "verification_method",
            "verification",
            "verified_at",
            "mailcow_provisioned",
            "dkim_selector",
            "dns_records",
            "dns_status",
            "mailbox_count",
            "alias_count",
            "last_error",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_dns_records(self, obj):
        return obj.required_dns_records()

    def get_verification(self, obj):
        return {
            "record_type": "TXT",
            "record_name": obj.verification_record_name,
            "record_value": obj.verification_token,
            "started_at": obj.verification_started_at,
            "last_attempt_at": obj.last_verification_attempt_at,
        }


class DomainCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=253)
    business = serializers.IntegerField(required=False, allow_null=True)


class ReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")
