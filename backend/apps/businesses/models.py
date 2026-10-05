from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Sum

from apps.core.models import TimeStampedModel


class Plan(TimeStampedModel):
    """Commercial plan. Limits are enforced by the Django control plane."""

    code = models.SlugField(max_length=40, unique=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    max_domains = models.PositiveIntegerField(default=3, validators=[MinValueValidator(1)])
    max_mailboxes = models.PositiveIntegerField(default=10, validators=[MinValueValidator(1)])
    max_aliases = models.PositiveIntegerField(default=50)
    default_mailbox_quota_mb = models.PositiveIntegerField(default=5120, validators=[MinValueValidator(1)])
    max_mailbox_quota_mb = models.PositiveIntegerField(default=5120, validators=[MinValueValidator(1)])
    total_storage_mb = models.PositiveIntegerField(
        default=51200,
        validators=[MinValueValidator(1)],
        help_text="Sum of all mailbox quotas a business may allocate.",
    )
    outbound_per_hour = models.PositiveIntegerField(default=100, validators=[MinValueValidator(1)])
    outbound_per_day = models.PositiveIntegerField(default=500, validators=[MinValueValidator(1)])
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["max_mailboxes", "name"]

    def __str__(self) -> str:
        return self.name


class Business(TimeStampedModel):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        SUSPENDED = "SUSPENDED", "Suspended"
        CLOSED = "CLOSED", "Closed"

    name = models.CharField(max_length=200)
    legal_name = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE, db_index=True)
    contact_person = models.CharField(max_length=200, blank=True)
    contact_email = models.EmailField()
    contact_phone = models.CharField(max_length=32, blank=True)
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="businesses")
    notes = models.TextField(blank=True)
    suspended_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "businesses"
        constraints = [models.UniqueConstraint(fields=["name"], name="uniq_business_name")]

    def __str__(self) -> str:
        return self.name

    @property
    def is_active(self) -> bool:
        return self.status == self.Status.ACTIVE

    def allocated_storage_mb(self, exclude_mailbox_id=None) -> int:
        qs = self.mailboxes.exclude(status="DELETING")
        if exclude_mailbox_id:
            qs = qs.exclude(pk=exclude_mailbox_id)
        return qs.aggregate(total=Sum("quota_mb"))["total"] or 0
