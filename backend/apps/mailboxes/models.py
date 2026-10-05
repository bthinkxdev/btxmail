from django.db import models
from django.db.models.functions import Lower

from apps.core.models import TimeStampedModel


class Mailbox(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        ACTIVE = "ACTIVE", "Active"
        SUSPENDED = "SUSPENDED", "Suspended"
        DISABLED = "DISABLED", "Disabled"
        FAILED = "FAILED", "Failed"
        DELETING = "DELETING", "Deleting"

    business = models.ForeignKey("businesses.Business", on_delete=models.PROTECT, related_name="mailboxes")
    domain = models.ForeignKey("domains.Domain", on_delete=models.PROTECT, related_name="mailboxes")
    local_part = models.CharField(max_length=64)
    email = models.EmailField(max_length=320, unique=True)
    display_name = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True)
    quota_mb = models.PositiveIntegerField()
    used_bytes = models.BigIntegerField(default=0)
    message_count = models.PositiveIntegerField(default=0)

    # Outbound protection
    outbound_suspended = models.BooleanField(default=False)
    outbound_suspended_reason = models.CharField(max_length=255, blank=True)
    outbound_suspended_at = models.DateTimeField(null=True, blank=True)
    outbound_limit_per_hour = models.PositiveIntegerField(null=True, blank=True)
    outbound_limit_per_day = models.PositiveIntegerField(null=True, blank=True)

    mailcow_id = models.CharField(max_length=320, blank=True, help_text="Mailcow username (the address).")
    last_login_at = models.DateTimeField(null=True, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)

    class Meta:
        ordering = ["email"]
        verbose_name_plural = "mailboxes"
        constraints = [models.UniqueConstraint(Lower("email"), name="uniq_mailbox_email_ci")]
        indexes = [models.Index(fields=["business", "status"])]

    def __str__(self) -> str:
        return self.email

    @property
    def quota_bytes(self) -> int:
        return self.quota_mb * 1024 * 1024

    def effective_hourly_limit(self) -> int:
        return self.outbound_limit_per_hour or self.business.plan.outbound_per_hour

    def effective_daily_limit(self) -> int:
        return self.outbound_limit_per_day or self.business.plan.outbound_per_day


class Alias(TimeStampedModel):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        DISABLED = "DISABLED", "Disabled"

    business = models.ForeignKey("businesses.Business", on_delete=models.PROTECT, related_name="aliases")
    domain = models.ForeignKey("domains.Domain", on_delete=models.PROTECT, related_name="aliases")
    source_address = models.EmailField(max_length=320, unique=True)
    destinations = models.JSONField(default=list, help_text="List of destination addresses.")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    mailcow_id = models.CharField(max_length=32, blank=True)

    class Meta:
        ordering = ["source_address"]
        verbose_name_plural = "aliases"
        constraints = [models.UniqueConstraint(Lower("source_address"), name="uniq_alias_source_ci")]

    def __str__(self) -> str:
        return f"{self.source_address} → {', '.join(self.destinations)}"
