from django.contrib import admin

from .models import User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("email", "full_name", "role", "business", "is_active", "totp_enabled", "last_login")
    list_filter = ("role", "is_active", "totp_enabled")
    search_fields = ("email", "full_name")
    readonly_fields = (
        "password",
        "last_login",
        "date_joined",
        "totp_secret_encrypted",
        "totp_pending_secret_encrypted",
        "recovery_code_hashes",
    )
    exclude = ("groups", "user_permissions")

    def has_module_permission(self, request):
        return getattr(request.user, "is_super_admin", False)

    has_view_permission = has_change_permission = has_add_permission = has_delete_permission = (
        lambda self, request, obj=None: getattr(request.user, "is_super_admin", False)
    )
