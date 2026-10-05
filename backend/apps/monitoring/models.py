from django.db import models


class HealthCheck(models.Model):
    class Status(models.TextChoices):
        OK = "OK", "OK"
        WARN = "WARN", "Warning"
        CRITICAL = "CRITICAL", "Critical"
        UNKNOWN = "UNKNOWN", "Unknown"

    component = models.CharField(max_length=64, db_index=True)
    status = models.CharField(max_length=10, choices=Status.choices)
    message = models.CharField(max_length=500, blank=True)
    details = models.JSONField(default=dict, blank=True)
    checked_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-checked_at"]
        indexes = [models.Index(fields=["component", "-checked_at"])]

    def __str__(self) -> str:
        return f"{self.component}: {self.status}"


class BlacklistCheck(models.Model):
    ip_address = models.GenericIPAddressField()
    zone = models.CharField(max_length=128)
    listed = models.BooleanField(default=False)
    response = models.CharField(max_length=255, blank=True)
    error = models.CharField(max_length=255, blank=True)
    checked_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-checked_at"]
        indexes = [models.Index(fields=["zone", "-checked_at"])]

    def __str__(self) -> str:
        return f"{self.ip_address}@{self.zone}: {'LISTED' if self.listed else 'clean'}"
