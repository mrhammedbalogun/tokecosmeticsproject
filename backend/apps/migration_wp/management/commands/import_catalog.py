"""Import a catalogue artifact into Postgres. Never opens a MariaDB connection.

Idempotent by design — see the per-object keys in the Plan-21 spec. Safe to run
repeatedly (dry run, rehearsal, cutover).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.catalog.models import Category, Tag

LEGACY_SOURCE = "wp_ng"

logger = logging.getLogger(__name__)


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
            cats, orphans = self._import_categories(data)
            tags = self._import_tags(data)
            self.stdout.write(
                f"categories: {cats}  tags: {tags}  orphan_parent_refs: {orphans}"
            )
            if self.dry_run:
                transaction.set_rollback(True)

    def _import_categories(self, data) -> tuple[int, int]:
        """WP product_cat terms -> Category, keyed on legacy_wp_id, slug preserved.

        A category is matched by legacy_wp_id first. If no row carries that WP
        term id yet, fall back to a slug match — the same category may already
        exist (created by staff in wp-admin, or left over from an earlier
        partial run) without the legacy id attached, and Category.slug is
        globally unique so blindly inserting would raise IntegrityError and
        abort the whole transaction. A slug match is *adopted*: its
        legacy_wp_id is set and its fields are refreshed from the artifact.
        Adoption is logged at INFO so the merge is never silent.

        Returns (category_count, orphan_parent_ref_count).
        """
        terms = [t for t in data["terms"] if t["taxonomy"] == "product_cat"]
        by_wp_id: dict[int, Category] = {}
        # First pass: create/update without parents so any input order works.
        for t in terms:
            term_id = t["term_id"]
            fields = {
                "name": t["name"],
                "slug": t["slug"],
                "description": t.get("description") or "",
            }
            cat = Category.objects.filter(legacy_wp_id=term_id).first()
            if cat is None:
                cat = Category.objects.filter(slug=t["slug"]).first()
                if cat is not None:
                    logger.info(
                        "Adopting existing category slug=%r (id=%s) into WP term_id=%s",
                        t["slug"], cat.pk, term_id,
                    )
                    cat.legacy_wp_id = term_id
            if cat is None:
                cat = Category(legacy_wp_id=term_id)
            for field, value in fields.items():
                setattr(cat, field, value)
            cat.save()
            by_wp_id[term_id] = cat

        # Second pass: wire parents now that every term in this artifact has a
        # row. A parent id that isn't in the artifact at all (deleted upstream,
        # or a data error) must not be silently dropped -- warn, count it, and
        # leave the child parentless so the dry-run summary surfaces it rather
        # than burying it in logs.
        orphan_count = 0
        for t in terms:
            parent_wp_id = t.get("parent") or 0
            if not parent_wp_id:
                continue
            parent = by_wp_id.get(parent_wp_id)
            if parent is None:
                orphan_count += 1
                logger.warning(
                    "Category %r (WP term_id=%s) references missing parent "
                    "WP term_id=%s; leaving parent unset",
                    t["slug"], t["term_id"], parent_wp_id,
                )
                continue
            cat = by_wp_id[t["term_id"]]
            cat.parent = parent
            cat.save(update_fields=["parent"])
        return len(terms), orphan_count

    def _import_tags(self, data) -> int:
        """WP product_tag terms -> Tag, keyed on slug.

        Tag has no legacy_wp_id, so slug is the only stable identity we have.
        update_or_create (not get_or_create) so a tag renamed in WordPress
        between rehearsal and cutover has its name refreshed here too, instead
        of being created once and left stale forever.
        """
        terms = [t for t in data["terms"] if t["taxonomy"] == "product_tag"]
        for t in terms:
            Tag.objects.update_or_create(slug=t["slug"], defaults={"name": t["name"]})
        return len(terms)
