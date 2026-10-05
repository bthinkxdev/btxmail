import hashlib
import secrets

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.core import crypto


class Role(models.TextChoices):
    SUPER_ADMIN = "SUPER_ADMIN", "Super Admin"
    OPS_ADMIN = "OPS_ADMIN", "Operations Admin"
    BUSINESS_ADMIN = "BUSINESS_ADMIN", "Business Admin"


PLATFORM_ROLES = {Role.SUPER_ADMIN, Role.OPS_ADMIN}


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra):
        if not email:
            raise ValueError("Email is required")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra)
        user.set_password(password)
        user.full_clean(exclude=["password"])
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra):
        extra.setdefault("role", Role.BUSINESS_ADMIN)
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email, password=None, **extra):
        extra.update(role=Role.SUPER_ADMIN, is_staff=True, is_superuser=True)
        return self._create_user(email, password, **extra)


class User(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=200, blank=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.BUSINESS_ADMIN, db_index=True)
    business = models.ForeignKey(
        "businesses.Business", null=True, blank=True, on_delete=models.CASCADE, related_name="users"
    )
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False, help_text="May log into the Django admin site.")
    date_joined = models.DateTimeField(default=timezone.now)
    must_change_password = models.BooleanField(default=False)
    password_changed_at = models.DateTimeField(null=True, blank=True)

    totp_secret_encrypted = models.TextField(blank=True, default="")
    totp_pending_secret_encrypted = models.TextField(blank=True, default="")
    totp_enabled = models.BooleanField(default=False)
    recovery_code_hashes = models.JSONField(default=list, blank=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        ordering = ["email"]
        constraints = [
            models.CheckConstraint(
                name="business_admin_requires_business",
                condition=(Q(role="BUSINESS_ADMIN", business__isnull=False) | ~Q(role="BUSINESS_ADMIN")),
            ),
            models.CheckConstraint(
                name="platform_staff_has_no_business",
                condition=(Q(role="BUSINESS_ADMIN") | Q(business__isnull=True)),
            ),
        ]

    def __str__(self) -> str:
        return self.email

    def clean(self):
        super().clean()
        self.email = (self.email or "").strip().lower()
        if self.role == Role.BUSINESS_ADMIN and not self.business_id:
            raise ValidationError({"business": "Business admins must belong to a business."})
        if self.role in PLATFORM_ROLES and self.business_id:
            raise ValidationError({"business": "Platform administrators cannot belong to a business."})

    # ---- roles -----------------------------------------------------------
    @property
    def is_platform_staff(self) -> bool:
        return self.role in PLATFORM_ROLES

    @property
    def is_super_admin(self) -> bool:
        return self.role == Role.SUPER_ADMIN

    # ---- TOTP ------------------------------------------------------------
    @property
    def totp_secret(self) -> str:
        return crypto.decrypt(self.totp_secret_encrypted)

    @property
    def totp_pending_secret(self) -> str:
        return crypto.decrypt(self.totp_pending_secret_encrypted)

    def set_pending_totp_secret(self, secret: str) -> None:
        self.totp_pending_secret_encrypted = crypto.encrypt(secret)

    def activate_pending_totp(self) -> None:
        self.totp_secret_encrypted = self.totp_pending_secret_encrypted
        self.totp_pending_secret_encrypted = ""
        self.totp_enabled = True

    def disable_totp(self) -> None:
        self.totp_secret_encrypted = ""
        self.totp_pending_secret_encrypted = ""
        self.totp_enabled = False
        self.recovery_code_hashes = []

    @staticmethod
    def _hash_code(code: str) -> str:
        normalized = code.replace("-", "").replace(" ", "").upper()
        return hashlib.sha256(normalized.encode()).hexdigest()

    def generate_recovery_codes(self, count: int = 10) -> list[str]:
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        codes = []
        for _ in range(count):
            raw = "".join(secrets.choice(alphabet) for _ in range(10))
            codes.append(f"{raw[:5]}-{raw[5:]}")
        self.recovery_code_hashes = [self._hash_code(c) for c in codes]
        return codes

    def consume_recovery_code(self, code: str) -> bool:
        digest = self._hash_code(code)
        hashes = list(self.recovery_code_hashes or [])
        for stored in hashes:
            if secrets.compare_digest(stored, digest):
                hashes.remove(stored)
                self.recovery_code_hashes = hashes
                self.save(update_fields=["recovery_code_hashes"])
                return True
        return False
