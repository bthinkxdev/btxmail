"""
Idempotent first-run setup, executed by the container entrypoint:

* creates the default plans (Starter / Business / Enterprise) if no plan exists;
* creates the first super admin from BOOTSTRAP_ADMIN_EMAIL / BOOTSTRAP_ADMIN_PASSWORD
  if no super admin exists yet (password must be changed at first login).
"""

import os

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.models import Role, User
from apps.businesses.models import Plan

DEFAULT_PLANS = [
    {
        "code": "starter",
        "name": "Starter",
        "description": "10 mailboxes, 5 GB each",
        "max_domains": 2,
        "max_mailboxes": 10,
        "max_aliases": 30,
        "default_mailbox_quota_mb": 5120,
        "max_mailbox_quota_mb": 5120,
        "total_storage_mb": 51200,
        "outbound_per_hour": 50,
        "outbound_per_day": 300,
    },
    {
        "code": "business",
        "name": "Business",
        "description": "50 mailboxes, 10 GB each",
        "max_domains": 5,
        "max_mailboxes": 50,
        "max_aliases": 200,
        "default_mailbox_quota_mb": 10240,
        "max_mailbox_quota_mb": 10240,
        "total_storage_mb": 512000,
        "outbound_per_hour": 100,
        "outbound_per_day": 500,
    },
    {
        "code": "enterprise",
        "name": "Enterprise",
        "description": "Negotiated limits, 25 GB+ per mailbox",
        "max_domains": 20,
        "max_mailboxes": 500,
        "max_aliases": 2000,
        "default_mailbox_quota_mb": 25600,
        "max_mailbox_quota_mb": 51200,
        "total_storage_mb": 5120000,
        "outbound_per_hour": 200,
        "outbound_per_day": 1000,
    },
]


class Command(BaseCommand):
    help = "Create default plans and the first super admin (idempotent)."

    @transaction.atomic
    def handle(self, *args, **options):
        if not Plan.objects.exists():
            for data in DEFAULT_PLANS:
                Plan.objects.create(**data)
            self.stdout.write(self.style.SUCCESS(f"Created {len(DEFAULT_PLANS)} default plans."))

        if User.objects.filter(role=Role.SUPER_ADMIN).exists():
            return
        email = os.environ.get("BOOTSTRAP_ADMIN_EMAIL", "").strip().lower()
        password = os.environ.get("BOOTSTRAP_ADMIN_PASSWORD", "")
        if not email or not password:
            self.stdout.write(
                self.style.WARNING(
                    "No super admin exists. Set BOOTSTRAP_ADMIN_EMAIL and BOOTSTRAP_ADMIN_PASSWORD, "
                    "or run: python manage.py createsuperuser"
                )
            )
            return
        if len(password) < 12:
            self.stderr.write("BOOTSTRAP_ADMIN_PASSWORD must be at least 12 characters; skipping.")
            return
        User.objects.create_superuser(
            email=email, password=password, full_name="Platform Owner", must_change_password=True
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Created super admin {email}. Change the password and enable 2FA at first login, "
                "then remove BOOTSTRAP_ADMIN_PASSWORD from the environment."
            )
        )
