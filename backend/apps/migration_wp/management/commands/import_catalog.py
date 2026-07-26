"""Import a catalogue artifact into Postgres. Never opens a MariaDB connection.

Idempotent by design — see the per-object keys in the Plan-21 spec. Safe to run
repeatedly (dry run, rehearsal, cutover).
"""
from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.migration_wp.importers.categories import import_categories, import_tags
from apps.migration_wp.importers.media import import_media
from apps.migration_wp.importers.products import import_products
from apps.migration_wp.importers.stock import import_stock
from apps.migration_wp.importers.variants import import_variants_and_prices


class Command(BaseCommand):
    """Import a catalogue JSON artifact produced by extract_wp_catalog.

    Dry-run contract: `--dry-run` rolls back the database via transaction.set_rollback,
    but that covers ORM writes ONLY. Any operation with side effects outside Postgres —
    S3 uploads, email, HTTP calls, filesystem writes — MUST check `self.dry_run` and
    skip before acting. A dry run that mutates external state is a broken review gate.
    """

    help = "Import a catalogue JSON artifact produced by extract_wp_catalog."

    def add_arguments(self, parser):
        parser.add_argument("artifact", help="path to catalog-export.json")
        parser.add_argument("--dry-run", action="store_true", help="report only, write nothing")
        parser.add_argument("--skip-media", action="store_true", help="skip S3 image upload")
        parser.add_argument("--skip-stock", action="store_true", help="skip the stock phase")
        parser.add_argument(
            "--force-stock",
            action="store_true",
            help="overwrite stock a human has edited (dangerous — see spec)",
        )
        parser.add_argument(
            "--skip-prices",
            action="store_true",
            help=(
                "skip writing Price rows entirely -- use for a post-cutover corrective "
                "run that must not clobber NGN prices a human has since edited in the "
                "admin (see _rewrite_prices)"
            ),
        )
        parser.add_argument(
            "--uploads-root",
            default="/mnt/wp-uploads-ng",
            help="read-only mount of wp-content/uploads",
        )

    def handle(self, *args, **options):
        self.dry_run = options["dry_run"]
        self.skip_prices = options["skip_prices"]
        data = json.loads(Path(options["artifact"]).read_text(encoding="utf-8"))

        if self.dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — no writes will be made"))

        with transaction.atomic():
            cats, orphans = import_categories(data)
            tags, skipped_tags = import_tags(data)
            products = import_products(data)
            variants, orphan_variants = import_variants_and_prices(data, self.skip_prices)
            summary = (
                f"categories: {cats}  tags: {tags} ({len(skipped_tags)} skipped)  "
                f"orphan_parent_refs: {orphans}  "
                f"products: {products}  variants: {variants}  "
                f"orphan_variants: {orphan_variants}"
            )

            if not options["skip_stock"]:
                seeded, protected, protected_messages = import_stock(
                    data, options["force_stock"]
                )
                for message in protected_messages:
                    self.stdout.write(message)
                summary = f"{summary}  stock: {seeded} seeded, {protected} protected"

            if not options["skip_media"]:
                copied, missing, orphan_images, missing_report = import_media(
                    data, options["uploads_root"], self.dry_run
                )
                for slug, rel_path in missing_report:
                    self.stdout.write(f"missing image: {slug} -> {rel_path}")
                summary = (
                    f"{summary}  media: {copied} copied, {missing} missing, "
                    f"{orphan_images} orphan_images"
                )

            self.stdout.write(summary)

            if self.dry_run:
                transaction.set_rollback(True)
