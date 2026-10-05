from django.contrib import admin

from .models import Alert

admin.site.register(Alert, list_display=("created_at", "severity", "title", "delivered", "acknowledged_at"))
