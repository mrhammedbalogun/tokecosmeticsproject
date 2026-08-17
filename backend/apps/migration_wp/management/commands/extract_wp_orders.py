"""Read one WooCommerce store's orders to a JSON artifact (Plan-23).

Same discipline as `extract_wp_customers`: 0600 at creation, never committed, deleted
after import. This artifact carries names, emails, phone numbers and full postal addresses
for 4,096 orders — less immediately dangerous than password hashes, more personal.

One store per invocation. `--store` labels the artifact and must match the prefix being
read; getting them out of step writes order numbers under the wrong prefix and links
orders to the wrong customers.
"""

from __future__ import annotations

import datetime
import decimal
import json
import os
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import LegacyStore
from apps.migration_wp import wp_reader

ARTIFACT_VERSION = 1


class _ArtifactEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (datetime.datetime, datetime.date)):
            return obj.isoformat()
        # HPOS money columns (`total_amount`, `tax_amount`, …) are SQL DECIMALs, so
        # pymysql hands them back as `Decimal` and json refuses them. Serialise as a
        # STRING, never a float: `transform_orders.money()` does `Decimal(str(value))`
        # and already documents strings as one of the shapes it accepts, so a string
        # round-trips exactly. A float would round the artifact before the importer's
        # reconciliation ever got to compare it against WooCommerce's own totals, which
        # would turn the one check that guards the money into a check that agrees with
        # its own error.
        if isinstance(obj, decimal.Decimal):
            return str(obj)
        return super().default(obj)


class Command(BaseCommand):
    help = "Extract one WooCommerce store's orders to JSON."

    def add_arguments(self, parser):
        parser.add_argument("--store", required=True, choices=[s.value for s in LegacyStore])
        parser.add_argument("--out", required=True)
        parser.add_argument(
            "--include-legacy-posts",
            action="store_true",
            help=(
                "also read pre-HPOS orders from posts/postmeta. Needed for legacy_intl, "
                "which has 13 orders from 2023 that HPOS never backfilled and that are "
                "absent from wc_orders entirely."
            ),
        )

    def handle(self, *args, **options):
        store = options["store"]
        out_path = Path(options["out"])
        self._validate_out_path(out_path)

        with wp_reader.wp_connection() as conn:
            orders = wp_reader.fetch_orders(conn)
            legacy_posts = []
            if options["include_legacy_posts"]:
                known = {int(o["id"]) for o in orders}
                # Only the ones HPOS genuinely missed. An order present in both tables is
                # the HPOS row's business; the posts copy is stale by definition.
                legacy_posts = [
                    r for r in wp_reader.fetch_legacy_post_orders(conn)
                    if int(r["id"]) not in known
                ]
                orders = orders + legacy_posts
            order_ids = [int(o["id"]) for o in orders]
            addresses = wp_reader.fetch_order_addresses(conn, order_ids)
            items = wp_reader.fetch_order_items(conn, order_ids)

        artifact = {
            "version": ARTIFACT_VERSION,
            "store": store,
            "table_prefix": settings.WP_TABLE_PREFIX,
            "orders": orders,
            "addresses": {str(k): v for k, v in addresses.items()},
            "items": {str(k): v for k, v in items.items()},
        }

        out_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(out_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(artifact, fh, indent=2, cls=_ArtifactEncoder)

        self.stdout.write(
            self.style.SUCCESS(
                f"Wrote {out_path} (0600): {len(orders)} orders from {store}"
                + (f", {len(legacy_posts)} of them pre-HPOS" if legacy_posts else "")
            )
        )
        self.stdout.write(
            self.style.WARNING(
                "This file contains customer names, emails, phones and addresses. Do not "
                "commit it; delete it after import."
            )
        )

    @staticmethod
    def _validate_out_path(out_path: Path) -> None:
        ancestor = out_path.parent
        while not ancestor.exists():
            parent = ancestor.parent
            if parent == ancestor:
                break
            ancestor = parent
        if not ancestor.is_dir():
            raise CommandError(
                f"--out path is not usable: nearest existing ancestor "
                f"'{ancestor}' is not a directory."
            )
