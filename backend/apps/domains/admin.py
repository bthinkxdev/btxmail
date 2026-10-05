from django.contrib import admin

from .models import Domain, DomainDNSStatus


class DNSStatusInline(admin.StackedInline):
    model = DomainDNSStatus
    can_delete = False
    readonly_fields = (
        "mx_status",
        "spf_status",
        "dkim_status",
        "dmarc_status",
        "ptr_status",
        "details",
        "last_checked",
    )


@admin.register(Domain)
class DomainAdmin(admin.ModelAdmin):
    list_display = ("name", "business", "status", "mailcow_provisioned", "verified_at")
    list_filter = ("status", "mailcow_provisioned")
    search_fields = ("name", "business__name")
    readonly_fields = ("verification_token", "dkim_public_record", "mailcow_provisioned", "last_error")
    inlines = [DNSStatusInline]
