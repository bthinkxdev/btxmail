from django.db import models


class SecurityEvent(models.Model):
    class EventType(models.TextChoices):
        LOGIN_BRUTE_FORCE = "LOGIN_BRUTE_FORCE", "Login brute force"
        HIGH_OUTBOUND_VOLUME = "HIGH_OUTBOUND_VOLUME", "High outbound volume"
        HIGH_BOUNCE_RATE = "HIGH_BOUNCE_RATE", "High bounce rate"
        SUSPICIOUS_LOGIN = "SUSPICIOUS_LOGIN", "Suspicious login"
        SPAM_ACTIVITY = "SPAM_ACTIVITY", "Spam activity"
        AUTH_FAILURE = "AUTH_FAILURE", "Authentication failures"
        RATE_LIMITED = "RATE_LIMITED", "Rate limit reached"
        PORTAL_LOCKOUT = "PORTAL_LOCKOUT", "Portal account lockout"

    class Severity(models.TextChoices):
        LOW = "LOW", "Low"
        MEDIUM = "MEDIUM", "Medium"
        HIGH = "HIGH", "High"
        CRITICAL = "CRITICAL", "Critical"

    class Action(models.TextChoices):
        NONE = "NONE", "None"
        ALERTED = "ALERTED", "Alerted"
        OUTBOUND_SUSPENDED = "OUTBOUND_SUSPENDED", "Outbound suspended"
        IP_BLOCKED = "IP_BLOCKED", "IP blocked"

    business = models.ForeignKey(
        "businesses.Business", null=True, blank=True, on_delete=models.CASCADE, related_name="security_events"
    )
    mailbox = models.ForeignKey(
        "mailboxes.Mailbox", null=True, blank=True, on_delete=models.SET_NULL, related_name="security_events"
    )
    subject = models.CharField(max_length=320, blank=True, help_text="Address or account the event concerns.")
    event_type = models.CharField(max_length=32, choices=EventType.choices, db_index=True)
    severity = models.CharField(max_length=8, choices=Severity.choices, default=Severity.MEDIUM, db_index=True)
    source_ip = models.GenericIPAddressField(null=True, blank=True)
    message_count = models.PositiveIntegerField(default=0)
    description = models.TextField(blank=True)
    details = models.JSONField(default=dict, blank=True)
    action_taken = models.CharField(max_length=24, choices=Action.choices, default=Action.NONE)
    fingerprint = models.CharField(max_length=128, blank=True, db_index=True)
    detected_at = models.DateTimeField(auto_now_add=True, db_index=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey("accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    resolution_note = models.TextField(blank=True)

    class Meta:
        ordering = ["-detected_at"]
        indexes = [models.Index(fields=["business", "-detected_at"])]

    def __str__(self) -> str:
        return f"{self.event_type} {self.subject}"

    @property
    def is_open(self) -> bool:
        return self.resolved_at is None
