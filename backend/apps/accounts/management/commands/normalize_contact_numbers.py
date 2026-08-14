"""One-off backfill: normalise stored contact numbers to strict E.164.

The registration/profile/address serializers enforce E.164 on every NEW write
(apps.core.phones), but rows migrated from WordPress hold national formats like
"08034138636" or "0703 123 4567". This command cleans them in place.

DRY-RUN BY DEFAULT — it prints what would change and writes nothing until --apply
is given. Run it once per environment after the accounts.0010 deploy:

    python manage.py normalize_contact_numbers            # report only
    python manage.py normalize_contact_numbers --apply    # write

Numbers without a "+" are parsed with a default region (--region, default NG:
the legacy customer base is overwhelmingly Nigerian and NG national numbers are
unambiguous). Anything that still fails to parse as a possible number is LEFT
UNTOUCHED and listed — a wrong guess stored silently is worse than a dirty value,
because the dirty value at least still says what the customer typed.

Order rows are deliberately not touched: their address snapshots are historical
records of what shipped where, and GIG capture reads the live Address row for
new shipments anyway.
"""

import phonenumbers
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.models import Address, User
from apps.core.phones import normalize_e164


def _renormalize(value: str, region: str) -> str | None:
    """E.164 for `value`, or None when it cannot be cleaned safely.

    Tries the strict rule first (covers "+234..." with noise), then a parse with
    the default region for bare national numbers. is_valid_number (not merely
    "possible") gates the region-assisted path — the whole point is to never
    store a guess that does not check out against the country's numbering plan.
    """
    raw = (value or "").strip()
    if not raw:
        return ""
    try:
        return normalize_e164(raw)
    except ValueError:
        pass
    try:
        parsed = phonenumbers.parse(raw, region)
    except phonenumbers.NumberParseException:
        return None
    if not phonenumbers.is_valid_number(parsed):
        return None
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


class Command(BaseCommand):
    help = "Normalise User.phone/User.whatsapp and Address.phone to E.164 (dry-run unless --apply)."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Write changes (default: report only).")
        parser.add_argument("--region", default="NG", help="Default region for numbers without '+' (default NG).")

    def handle(self, *args, **options):
        apply_changes: bool = options["apply"]
        region: str = options["region"].upper()

        changed = 0
        skipped: list[str] = []

        with transaction.atomic():
            for model, fields, describe in (
                (User, ("phone", "whatsapp"), lambda o: o.email),
                (Address, ("phone",), lambda o: f"address #{o.pk} ({o.user.email})"),
            ):
                for obj in model.objects.exclude(**{f: "" for f in fields}).iterator():
                    updates = []
                    for field in fields:
                        old = getattr(obj, field)
                        if not old:
                            continue
                        new = _renormalize(old, region)
                        if new is None:
                            skipped.append(f"{describe(obj)} {field}={old!r}")
                        elif new != old:
                            self.stdout.write(f"{describe(obj)}: {field} {old!r} -> {new!r}")
                            setattr(obj, field, new)
                            updates.append(field)
                    if updates:
                        changed += 1
                        if apply_changes:
                            obj.save(update_fields=updates)

            if not apply_changes:
                transaction.set_rollback(True)

        for line in skipped:
            self.stdout.write(self.style.WARNING(f"SKIPPED (could not parse): {line}"))
        verb = "updated" if apply_changes else "would update"
        self.stdout.write(self.style.SUCCESS(
            f"{verb} {changed} row(s); {len(skipped)} value(s) left untouched."
            + ("" if apply_changes else " Re-run with --apply to write.")
        ))
