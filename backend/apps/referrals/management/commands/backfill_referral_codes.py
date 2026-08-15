"""Mint referral codes for accounts that predate the programme.

`ensure_profile` creates a code the first time a customer opens their referral page, so
this command is not needed for the feature to work. It exists so that a code EXISTS
before a customer goes looking — the shop can then put someone's code in a newsletter,
and support can read one out over the phone, without the customer having to visit a page
first to bring it into being.

Idempotent: accounts that already have a profile are skipped, so it can be re-run after
every migration batch.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.models import User
from apps.referrals.models import ReferralProfile
from apps.referrals.services import ensure_profile


class Command(BaseCommand):
    help = "Create referral profiles (and codes) for customers that do not have one."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Report how many would be created, write nothing.",
        )
        parser.add_argument(
            "--batch", type=int, default=500,
            help="Commit every N accounts (default 500).",
        )

    def handle(self, *args, **options):
        # Staff-only accounts are skipped: they are administrators, not customers, and
        # minting them a referral code invites the one thing the terms prohibit outright.
        # A staff member who also shops has is_staff True, so this is deliberately
        # conservative — better a real referrer has to open the page once than an
        # employee finds a code waiting for them.
        missing = (
            User.objects.filter(is_active=True, is_staff=False)
            .exclude(pk__in=ReferralProfile.objects.values("user_id"))
            .order_by("pk")
        )
        total = missing.count()
        if options["dry_run"]:
            self.stdout.write(f"{total} account(s) would get a referral code.")
            return

        created = 0
        batch: list = []
        for user in missing.iterator(chunk_size=options["batch"]):
            batch.append(user)
            if len(batch) >= options["batch"]:
                created += self._flush(batch)
                batch = []
        created += self._flush(batch)
        self.stdout.write(self.style.SUCCESS(f"Created {created} referral profile(s)."))

    def _flush(self, batch: list) -> int:
        if not batch:
            return 0
        with transaction.atomic():
            for user in batch:
                ensure_profile(user)
        return len(batch)
