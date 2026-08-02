"""Import an order artifact into Postgres. Never opens a MariaDB connection.

Idempotent on `(source, legacy_number)`. Safe to run repeatedly.
"""

from __future__ import annotations

import csv
import json
import os
from datetime import timedelta
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import LegacyStore
from apps.migration_wp.importers.orders import import_orders
from apps.migration_wp.transform_orders import money

#: How far back the chase CSV reaches. Decided 2026-08-01 with the `expired` ruling: the
#: 2,277 unpaid bank transfers become `expired` rather than filling a working queue, and
#: this window is the compromise — recent enough that the customer might still pay, short
#: enough that the list is workable by hand.
CHASE_WINDOW_DAYS = 30


class Command(BaseCommand):
    help = "Import an order JSON artifact produced by extract_wp_orders."

    def add_arguments(self, parser):
        parser.add_argument("artifact", help="path to an orders-<store>.json artifact")
        parser.add_argument("--dry-run", action="store_true", help="report only, write nothing")
        parser.add_argument(
            "--since",
            default=None,
            help="only import orders created at or after this timestamp (cutover delta)",
        )
        parser.add_argument(
            "--chase-csv",
            default=None,
            help=(
                f"write the last {CHASE_WINDOW_DAYS} days of unpaid bank-transfer orders "
                "to this path so they can be chased by hand. CONTAINS CUSTOMER NAMES AND "
                "EMAILS: written 0600, gitignored, delete after use."
            ),
        )

    def handle(self, *args, **options):
        path = Path(options["artifact"])
        if not path.is_file():
            raise CommandError(f"No such artifact: {path}")

        data = json.loads(path.read_text(encoding="utf-8"))
        store = data.get("store")
        if store not in {s.value for s in LegacyStore}:
            raise CommandError(
                f"Artifact declares store={store!r}, which is not one of "
                f"{sorted(s.value for s in LegacyStore)}."
            )

        dry_run = options["dry_run"]
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — no writes will be made"))

        with transaction.atomic():
            summary = import_orders(data, since=options["since"])
            reconciliation = self._reconcile(data, store)
            if options["chase_csv"]:
                self._write_chase_csv(data, Path(options["chase_csv"]))
            if dry_run:
                transaction.set_rollback(True)

        width = max(len(k) for k in summary)
        for key, value in summary.items():
            self.stdout.write(f"  {key.ljust(width)}  {value}")

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Reconciliation (source vs imported)"))
        for line in reconciliation:
            self.stdout.write(f"  {line}")

        self.stdout.write(
            self.style.SUCCESS(
                f"{'Would import' if dry_run else 'Imported'} {summary['created']} new "
                f"orders from {store}."
            )
        )

    def _reconcile(self, data: dict, store: str) -> list[str]:
        """Source totals vs what landed, per currency.

        THIS IS THE SAFETY NET FOR EVERY ROUNDING AND SKIP DECISION in the transforms.
        `money()` cannot raise on a bad amount the way `payments/money.py` does — it has
        4,096 historical rows to get through — so instead nothing is lost silently: the
        source is summed here from the artifact and compared with what is now in the
        database. A mismatch is a number a human reads, not a rounding nobody sees.
        """
        from apps.orders.models import Order

        source: dict[str, list] = {}
        for row in data["orders"]:
            code = (row.get("currency") or "?").upper()
            bucket = source.setdefault(code, [0, money(0)])
            bucket[0] += 1
            bucket[1] += money(row.get("total_amount"))

        lines = []
        for code in sorted(source):
            src_count, src_total = source[code]
            landed = Order.objects.filter(source=store, currency_id=code)
            got_count = landed.count()
            got_total = sum((o.grand_total for o in landed), money(0))
            drift = got_total - src_total
            flag = "" if not drift else f"   <-- DRIFT {drift}"
            lines.append(
                f"{code}: source {src_count} orders / {src_total}  ->  "
                f"imported {got_count} / {got_total}{flag}"
            )
            if src_count != got_count:
                lines.append(
                    f"     {src_count - got_count} not imported — see the skip counts above; "
                    "trashed and currency-less rows are deliberate."
                )
        return lines or ["(nothing to reconcile)"]

    def _write_chase_csv(self, data: dict, out_path: Path) -> None:
        """Recent unpaid bank transfers, for chasing by hand.

        The alternative — importing 2,277 unpaid orders as `pending_payment` — would put a
        queue in the admin that nobody can work, and a queue nobody works is a queue nobody
        reads. This is the short list instead.
        """
        cutoff = (timezone.now() - timedelta(days=CHASE_WINDOW_DAYS)).strftime("%Y-%m-%d")
        addresses = data.get("addresses", {})

        rows = []
        for row in data["orders"]:
            status = (row.get("status") or "").replace("wc-", "")
            if status != "on-hold" or row.get("date_paid_gmt"):
                continue
            created = str(row.get("date_created_gmt") or "")
            if created[:10] < cutoff:
                continue
            billing = (addresses.get(str(row["id"])) or {}).get("billing") or {}
            rows.append(
                {
                    "wp_order_id": row["id"],
                    "created": created,
                    "currency": row.get("currency"),
                    "total": money(row.get("total_amount")),
                    "name": f"{billing.get('first_name') or ''} {billing.get('last_name') or ''}".strip(),
                    "email": row.get("billing_email") or billing.get("email") or "",
                    "phone": billing.get("phone") or "",
                }
            )

        out_path.parent.mkdir(parents=True, exist_ok=True)
        # 0600 at creation, like every other artifact carrying customer data.
        fd = os.open(out_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(
                fh,
                fieldnames=["wp_order_id", "created", "currency", "total", "name", "email", "phone"],
            )
            writer.writeheader()
            writer.writerows(rows)

        self.stdout.write(
            self.style.WARNING(
                f"Wrote {out_path} (0600): {len(rows)} unpaid bank transfers from the last "
                f"{CHASE_WINDOW_DAYS} days. Contains customer names and emails — delete "
                "after use."
            )
        )
