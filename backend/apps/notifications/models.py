from django.db import models


class Alert(models.Model):
    class Severity(models.TextChoices):
        INFO = "INFO", "Info"
        WARNING = "WARNING", "Warning"
        CRITICAL = "CRITICAL", "Critical"

    key = models.CharField(max_length=200, db_index=True, help_text="Deduplication key.")
    severity = models.CharField(max_length=10, choices=Severity.choices, default=Severity.WARNING)
    title = models.CharField(max_length=255)
    message = models.TextField()
    business = models.ForeignKey(
        "businesses.Business", null=True, blank=True, on_delete=models.SET_NULL, related_name="alerts"
    )
    delivered = models.BooleanField(default=False)
    channels_delivered = models.JSONField(default=list, blank=True)
    delivery_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"[{self.severity}] {self.title}"
