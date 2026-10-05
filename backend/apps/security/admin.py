from django.contrib import admin

from .models import SecurityEvent


@admin.register(SecurityEvent)
class SecurityEventAdmin(admin.ModelAdmin):
    list_display = ("detected_at", "event_type", "severity", "subject", "action_taken", "resolved_at")
    list_filter = ("event_type", "severity", "action_taken")
    search_fields = ("subject",)
