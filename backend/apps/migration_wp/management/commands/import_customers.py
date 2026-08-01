"""Import a customer artifact into Postgres. Never opens a MariaDB connection.

Idempotent on `(store, wp_user_id)`. Safe to run repeatedly — dry run, rehearsal, and the
Plan-27 cutover delta — which is the whole point: the rehearsal is only meaningful if the
real run does the same thing.
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import LegacyStore
from apps.migration_wp.importers.customers import import_customers


class Command(BaseCommand):
    help = "Import a customer JSON artifact produced by extract_wp_customers."

    def add_arguments(self, parser):
        parser.add_argument("artifact", help="path to a customers-<store>.json artifact")
        parser.add_argument("--dry-run", action="store_true", help="report only, write nothing")
        parser.add_argument(
            "--since",
            default=None,
            help=(
                "only import rows with user_registered >= this timestamp "
                "(e.g. 2026-08-01 or 2026-08-01 12:00:00). For the Plan-27 cutover delta. "
                "NOTE: this filters on REGISTRATION DATE, so it catches customers who "
                "signed up after the rehearsal — it does not catch edits to customers who "
                "already existed. Those are handled by the importer's own idempotency, "
                "which deliberately leaves an already-imported account alone."
            ),
        )

    def handle(self, *args, **options):
        path = Path(options["artifact"])
        if not path.is_file():
            raise CommandError(f"No such artifact: {path}")

        data = json.loads(path.read_text(encoding="utf-8"))
        store = data.get("store")
        if store not in {s.value for s in LegacyStore}:
            # An artifact with no store, or a store this codebase does not know, would
            # write LegacyIdentity rows that nothing can ever match again.
            raise CommandError(
                f"Artifact declares store={store!r}, which is not one of "
                f"{sorted(s.value for s in LegacyStore)}."
            )

        dry_run = options["dry_run"]
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — no writes will be made"))

        with transaction.atomic():
            summary = import_customers(data, since=options["since"])
            if dry_run:
                transaction.set_rollback(True)

        width = max(len(k) for k in summary)
        for key, value in summary.items():
            self.stdout.write(f"  {key.ljust(width)}  {value}")

        self.stdout.write(
            self.style.SUCCESS(
                f"{'Would import' if dry_run else 'Imported'} {summary['created']} new "
                f"customers from {store}."
            )
        )
