from django.core.management.base import BaseCommand, CommandError

from apps.mailcow import health
from apps.mailcow.client import get_client
from apps.mailcow.exceptions import MailcowError


class Command(BaseCommand):
    help = "Verify the control plane can reach and authenticate to the Mailcow API."

    def handle(self, *args, **options):
        client = get_client()
        try:
            version = health.version(client)
            containers = health.container_status(client)
        except MailcowError as exc:
            raise CommandError(f"Mailcow check failed: {exc.message}") from exc
        self.stdout.write(self.style.SUCCESS(f"Mailcow reachable (version {version or 'unknown'})."))
        for name, state in sorted(containers.items()):
            style = self.style.SUCCESS if state == "running" else self.style.ERROR
            self.stdout.write(style(f"  {name:<28} {state}"))
