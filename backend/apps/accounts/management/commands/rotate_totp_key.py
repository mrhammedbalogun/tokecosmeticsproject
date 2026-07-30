"""Re-encrypt every staff TOTP secret under the current primary key.

WHY KEY ROTATION HAS TO BE POSSIBLE AT ALL. `TOTP_ENCRYPTION_KEY` is deliberately NOT
derived from `SECRET_KEY` (see `config/settings/base.py`), and the whole point of that
separation is that either can be rotated without the other. A rotation you cannot
perform is a key you can never retire, which is the same as not having separated them.

THE PROCEDURE, which is the same shape as Django's own `SECRET_KEY_FALLBACKS` and is
written out in `docs/runbooks/admin-gate.md` §6:

1. Generate a new key.
2. Set `TOTP_ENCRYPTION_KEY` to it and put the OLD key in
   `TOTP_ENCRYPTION_KEY_FALLBACKS`. Restart. Nothing breaks: `MultiFernet` encrypts with
   the primary and decrypts with either.
3. Run this command. Every row is rewritten under the new key.
4. Empty `TOTP_ENCRYPTION_KEY_FALLBACKS`. Restart. The old key is now retired.

Step 4 is the one that actually completes the rotation, and it is the one that is easy
to skip — so the runbook says to verify by confirming a staff login still works with the
fallback list empty.

SAFE TO RUN TWICE, and safe to interrupt: each row is read through the full key list and
written under the primary, so a half-finished run leaves a mixture that every step of
the procedure above already tolerates.
"""
from django.core.management.base import BaseCommand

from apps.accounts.models import StaffTOTP
from apps.accounts.totp import decrypt_secret, encrypt_secret


class Command(BaseCommand):
    help = "Re-encrypt every staff TOTP secret under the current TOTP_ENCRYPTION_KEY."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be rewritten without writing anything.",
        )

    def handle(self, *args, **options):
        rows = list(StaffTOTP.objects.all())
        if not rows:
            self.stdout.write("No staff TOTP enrolments to rotate.")
            return

        rewritten = 0
        for row in rows:
            # Deliberately NOT wrapped in try/except. A row that will not decrypt means
            # the key it was written under is in neither the primary slot nor the
            # fallbacks — a configuration emergency, and continuing past it would leave
            # the operator believing the rotation succeeded while one administrator is
            # locked out. Fail loudly, on the first one.
            secret = decrypt_secret(row.secret_ciphertext)
            if options["dry_run"]:
                rewritten += 1
                continue
            row.secret_ciphertext = encrypt_secret(secret)
            row.save(update_fields=["secret_ciphertext", "updated_at"])
            rewritten += 1

        verb = "would be rewritten" if options["dry_run"] else "rewritten"
        self.stdout.write(
            self.style.SUCCESS(f"{rewritten} staff TOTP secret(s) {verb} under the primary key.")
        )
        if not options["dry_run"]:
            self.stdout.write(
                "Now empty TOTP_ENCRYPTION_KEY_FALLBACKS and restart — that is the step "
                "that actually retires the old key. Confirm a staff login still works "
                "afterwards."
            )
