import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.models import TimeStampedModel


def generate_verification_token() -> str:
    return f"{settings.DOMAIN_VERIFICATION_TOKEN_PREFIX}{secrets.token_hex(16)}"


class Domain(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING_VERIFICATION = "PENDING_VERIFICATION", "Pending verification"
        PROVISIONING = "PROVISIONING", "Provisioning"
        DNS_PENDING = "DNS_PENDING", "Awaiting DNS"
        ACTIVE = "ACTIVE", "Active"
        PROVISIONING_FAILED = "PROVISIONING_FAILED", "Provisioning failed"
        SUSPENDED = "SUSPENDED", "Suspended"
        DELETING = "DELETING", "Deleting"

    class VerificationMethod(models.TextChoices):
        DNS_TXT = "DNS_TXT", "DNS TXT record"
        MANUAL = "MANUAL", "Manually verified by staff"

    PROVISIONED_STATES = {Status.DNS_PENDING, Status.ACTIVE, Status.SUSPENDED}

    business = models.ForeignKey("businesses.Business", on_delete=models.PROTECT, related_name="domains")
    name = models.CharField(max_length=253, unique=True)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.PENDING_VERIFICATION, db_index=True)
    verification_method = models.CharField(
        max_length=16, choices=VerificationMethod.choices, default=VerificationMethod.DNS_TXT
    )
    verification_token = models.CharField(max_length=80, default=generate_verification_token, editable=False)
    verification_started_at = models.DateTimeField(default=timezone.now)
    verified_at = models.DateTimeField(null=True, blank=True)
    last_verification_attempt_at = models.DateTimeField(null=True, blank=True)
    mailcow_provisioned = models.BooleanField(default=False)
    dkim_selector = models.CharField(max_length=63, blank=True)
    dkim_public_record = models.TextField(blank=True, help_text="Full DKIM TXT value as served by Mailcow.")
    provisioning_attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    @property
    def is_provisioned(self) -> bool:
        return self.mailcow_provisioned and self.status in self.PROVISIONED_STATES

    @property
    def verification_record_name(self) -> str:
        return f"{settings.DOMAIN_VERIFICATION_PREFIX}.{self.name}"

    @property
    def dkim_record_name(self) -> str:
        selector = self.dkim_selector or settings.DKIM_SELECTOR
        return f"{selector}._domainkey.{self.name}"

    def required_dns_records(self) -> list[dict]:
        records = [
            {
                "purpose": "VERIFICATION",
                "type": "TXT",
                "name": self.verification_record_name,
                "value": self.verification_token,
                "required": self.status == self.Status.PENDING_VERIFICATION,
            },
            {
                "purpose": "MX",
                "type": "MX",
                "name": self.name,
                "value": settings.MAIL_HOSTNAME,
                "priority": 10,
                "required": True,
            },
            {"purpose": "SPF", "type": "TXT", "name": self.name, "value": settings.SPF_RECORD, "required": True},
            {
                "purpose": "DMARC",
                "type": "TXT",
                "name": f"_dmarc.{self.name}",
                "value": settings.DMARC_RECORD,
                "required": False,
            },
            {
                "purpose": "AUTODISCOVER",
                "type": "CNAME",
                "name": f"autodiscover.{self.name}",
                "value": settings.MAIL_HOSTNAME,
                "required": False,
            },
            {
                "purpose": "AUTOCONFIG",
                "type": "CNAME",
                "name": f"autoconfig.{self.name}",
                "value": settings.MAIL_HOSTNAME,
                "required": False,
            },
        ]
        if self.dkim_public_record:
            records.insert(
                3,
                {
                    "purpose": "DKIM",
                    "type": "TXT",
                    "name": self.dkim_record_name,
                    "value": self.dkim_public_record,
                    "required": True,
                },
            )
        return records


class DomainDNSStatus(models.Model):
    class Result(models.TextChoices):
        PASS = "PASS", "Pass"
        FAIL = "FAIL", "Fail"
        WARN = "WARN", "Warning"
        UNKNOWN = "UNKNOWN", "Not checked"

    domain = models.OneToOneField(Domain, on_delete=models.CASCADE, related_name="dns_status")
    mx_status = models.CharField(max_length=8, choices=Result.choices, default=Result.UNKNOWN)
    spf_status = models.CharField(max_length=8, choices=Result.choices, default=Result.UNKNOWN)
    dkim_status = models.CharField(max_length=8, choices=Result.choices, default=Result.UNKNOWN)
    dmarc_status = models.CharField(max_length=8, choices=Result.choices, default=Result.UNKNOWN)
    ptr_status = models.CharField(max_length=8, choices=Result.choices, default=Result.UNKNOWN)
    details = models.JSONField(default=dict, blank=True)
    last_checked = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "domain DNS status"
        verbose_name_plural = "domain DNS statuses"

    def __str__(self) -> str:
        return f"DNS status for {self.domain}"

    @property
    def is_ready(self) -> bool:
        P = self.Result.PASS
        return self.mx_status == P and self.spf_status == P and self.dkim_status == P
