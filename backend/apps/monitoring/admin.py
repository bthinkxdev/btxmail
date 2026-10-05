from django.contrib import admin

from .models import BlacklistCheck, HealthCheck

admin.site.register(HealthCheck, list_display=("checked_at", "component", "status", "message"))
admin.site.register(BlacklistCheck, list_display=("checked_at", "ip_address", "zone", "listed", "error"))
