"""Idempotent demo seed for the bank_transfer gateway's SiteSettings.

Run manually before a checkout demo/checkpoint:

    uv run python manage.py seed_bank_transfer_demo

These are PLACEHOLDER test values so the bank_transfer `initiate()` returns real-looking
bank details; Hammed swaps in the live merchant account later. This is a management
command (not a data migration) on purpose: it must NOT run during the test suite, whose
bank_transfer test creates its own `bank_transfer.account_number` SiteSetting (a unique
key that a migration seed would collide with). `update_or_create` makes re-runs safe.
"""
from django.core.management.base import BaseCommand

from apps.core.models import SiteSetting

DEMO_SETTINGS = {
    "bank_transfer.bank_name": "Demo Bank PLC",
    "bank_transfer.account_name": "Toke Cosmetics Ltd",
    "bank_transfer.account_number": "0123456789",
}


class Command(BaseCommand):
    help = "Seed placeholder bank_transfer.* SiteSettings for the checkout demo (idempotent)."

    def handle(self, *args, **options):
        for key, value in DEMO_SETTINGS.items():
            SiteSetting.objects.update_or_create(
                key=key, defaults={"value": value, "value_type": "str"}
            )
            self.stdout.write(f"  set {key} = {value}")
        self.stdout.write(self.style.SUCCESS("bank_transfer demo SiteSettings seeded."))
