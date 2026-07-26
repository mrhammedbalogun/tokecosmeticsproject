"""Import a catalogue artifact into Postgres. Never opens a MariaDB connection.

Idempotent by design — see the per-object keys in the Plan-21 spec. Safe to run
repeatedly (dry run, rehearsal, cutover).
"""
from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.catalog.models import Category, Tag

LEGACY_SOURCE = "wp_ng"


class Command(BaseCommand):
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
            "--uploads-root",
            default="/mnt/wp-uploads-ng",
            help="read-only mount of wp-content/uploads",
        )

    def handle(self, *args, **options):
        self.dry_run = options["dry_run"]
        data = json.loads(Path(options["artifact"]).read_text(encoding="utf-8"))

        if self.dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — no writes will be made"))

        with transaction.atomic():
            cats = self._import_categories(data)
            tags = self._import_tags(data)
            self.stdout.write(f"categories: {cats}  tags: {tags}")
            if self.dry_run:
                transaction.set_rollback(True)

    def _import_categories(self, data) -> int:
        """WP product_cat terms -> Category, keyed on legacy_wp_id, slug preserved."""
        terms = [t for t in data["terms"] if t["taxonomy"] == "product_cat"]
        by_wp_id: dict[int, Category] = {}
        # First pass: create/update without parents so any input order works.
        for t in terms:
            cat, _ = Category.objects.update_or_create(
                legacy_wp_id=t["term_id"],
                defaults={
                    "name": t["name"],
                    "slug": t["slug"],
                    "description": t.get("description") or "",
                },
            )
            by_wp_id[t["term_id"]] = cat
        # Second pass: wire parents. All 40 live terms are flat, but a nested term
        # appearing at cutover must not silently lose its parent.
        for t in terms:
            parent_wp_id = t.get("parent") or 0
            if parent_wp_id and parent_wp_id in by_wp_id:
                cat = by_wp_id[t["term_id"]]
                cat.parent = by_wp_id[parent_wp_id]
                cat.save(update_fields=["parent"])
        return len(terms)

    def _import_tags(self, data) -> int:
        terms = [t for t in data["terms"] if t["taxonomy"] == "product_tag"]
        for t in terms:
            Tag.objects.get_or_create(slug=t["slug"], defaults={"name": t["name"]})
        return len(terms)
