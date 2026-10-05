from django.contrib import admin

from .models import Alias, Mailbox


@admin.register(Mailbox)
class MailboxAdmin(admin.ModelAdmin):
    """Read-only: changes must go through the portal so Mailcow stays in sync."""

    list_display = ("email", "business", "status", "quota_mb", "outbound_suspended", "last_login_at")
    list_filter = ("status", "outbound_suspended")
    search_fields = ("email", "display_name", "business__name")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Alias)
class AliasAdmin(admin.ModelAdmin):
    list_display = ("source_address", "business", "status")
    search_fields = ("source_address",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
