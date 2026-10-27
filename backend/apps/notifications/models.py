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


class PushSubscription(models.Model):
    """One browser/device registration for Web Push. Deleted when the push service reports it gone."""

    user = models.ForeignKey("accounts.User", on_delete=models.CASCADE, related_name="push_subscriptions")
    endpoint = models.URLField(max_length=700, unique=True)
    p256dh = models.CharField(max_length=255)
    auth = models.CharField(max_length=255)
    user_agent = models.CharField(max_length=300, blank=True)
    active = models.BooleanField(default=True)
    failure_count = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    last_success_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.user_id}:{self.endpoint[:40]}"


class NotificationPreference(models.Model):
    """Per-user opt-outs by category. A missing row means everything is on."""

    user = models.OneToOneField("accounts.User", on_delete=models.CASCADE, related_name="push_preference")
    new_mail = models.BooleanField(default=True)
    security = models.BooleanField(default=True)
    domains = models.BooleanField(default=True)
    system = models.BooleanField(default=True)

    def __str__(self) -> str:
        return f"preferences:{self.user_id}"


class MailWatch(models.Model):
    """A mailbox whose incoming mail notifies this portal user (own mailbox is implicit)."""

    user = models.ForeignKey("accounts.User", on_delete=models.CASCADE, related_name="mail_watches")
    mailbox = models.ForeignKey("mailboxes.Mailbox", on_delete=models.CASCADE, related_name="watchers")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "mailbox"], name="unique_mail_watch")]

    def __str__(self) -> str:
        return f"{self.user_id}->{self.mailbox_id}"
