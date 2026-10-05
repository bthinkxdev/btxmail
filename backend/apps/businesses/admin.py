from django.contrib import admin

from .models import Business, Plan


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "code",
        "max_domains",
        "max_mailboxes",
        "max_mailbox_quota_mb",
        "total_storage_mb",
        "outbound_per_hour",
        "outbound_per_day",
        "is_active",
    )


@admin.register(Business)
class BusinessAdmin(admin.ModelAdmin):
    list_display = ("name", "status", "plan", "contact_email", "created_at")
    list_filter = ("status", "plan")
    search_fields = ("name", "legal_name", "contact_email")
