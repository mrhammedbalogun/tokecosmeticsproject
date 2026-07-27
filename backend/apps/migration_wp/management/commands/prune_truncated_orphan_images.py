"""ONE-SHOT cleanup for the max_length=100 image-path truncation defect.

DELETE THIS COMMAND once the production run is verified. Git history keeps it
and its tests as the permanent record. It must not survive into the era when
staff can upload images through the admin (Plan-17), because a generic
"prune orphans" tool is a loaded gun: `importers/media.py` deliberately refuses
to delete orphans at all, and that no-delete stance must remain the only
standing policy.

THE DEFECT. ImageField's default max_length=100 silently truncates -- storage
never raises -- so 39 of 207 image paths were stored cut short, which broke the
importer's dedupe key. The field was widened to IMAGE_PATH_MAX and the import
re-run, creating correct rows and leaving the truncated ones behind.

WHY TWO PREDICATES. "Key is not in the source" is exactly the predicate media.py
refuses to delete on, because it cannot tell a stale row from an image a staff
member uploaded by hand. And "path is exactly 100 chars" is not safe alone
either: one live image's genuine path happens to be exactly 100 characters. So a
row is only ever selected when BOTH hold:

  1. its dedupe key is absent from the artifact-derived canonical key set, AND
  2. its stored path is exactly 100 characters (the truncation fingerprint).

Each predicate is the other's safety net. Predicate 1 protects the legitimate
100-char image; predicate 2 protects hand-uploads and any row whose source file
merely went missing between runs.

WHY ROWS ONLY. S3 bucket versioning is OFF, so deleting an object is
unrecoverable, while a deleted row is restorable from the nightly Postgres dump.
This command therefore deletes rows and writes the storage keys to a manifest;
the objects themselves are swept in Plan-25/26 AFTER versioning is enabled.

WHY NO FILESYSTEM ACCESS. The canonical key set is derived from the artifact
alone -- deliberately NOT filtered by whether each source file still exists, the
way media.py filters it. That makes this command's protected set strictly WIDER
than media.py's, and it means the command never reads the WordPress uploads
tree at all.
"""
from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models.functions import Length

from apps.catalog.models import ProductImage
from apps.migration_wp.importers.common import LEGACY_SOURCE
from apps.migration_wp.importers.media import _dedupe_key
from apps.migration_wp.transform import ordered_attachment_ids

TRUNCATED_LEN = 100


def canonical_keys(data) -> set[str]:
    """Every dedupe key the source could legitimately produce.

    Mirrors media.py's key construction (`<attachment_id>-<filename>`) but
    without its source-file-exists check, so a file that vanished from the
    uploads tree still protects its row here.
    """
    attachments: dict[str, str] = data["attachments"]
    meta_all: dict[str, dict] = data["meta"]
    keys: set[str] = set()
    for row in data["products"]:
        product_meta = meta_all.get(str(row["ID"]), {})
        for attachment_id in ordered_attachment_ids(product_meta):
            rel_path = attachments.get(str(attachment_id))
            if rel_path is None:
                continue
            keys.add(f"{attachment_id}-{Path(rel_path).name}")
    return keys


class Command(BaseCommand):
    help = "One-shot: delete ProductImage rows left behind by the path-truncation defect."

    def add_arguments(self, parser):
        parser.add_argument("artifact", help="Path to catalog-export.json from the real import.")
        parser.add_argument(
            "--apply", action="store_true",
            help="Actually delete. Without this the command only reports (the default).",
        )
        parser.add_argument(
            "--expect", type=int, default=None,
            help="Abort without deleting unless exactly this many rows are selected.",
        )
        parser.add_argument(
            "--manifest", default=None,
            help="Write the storage keys of deleted rows here, for the later S3 sweep.",
        )

    def handle(self, *args, **options):
        artifact = Path(options["artifact"])
        if not artifact.exists():
            raise CommandError(f"artifact not found: {artifact}")

        keys = canonical_keys(json.loads(artifact.read_text(encoding="utf-8")))
        self.stdout.write(f"Canonical keys in artifact: {len(keys)}")

        truncated = list(
            ProductImage.objects
            .select_related("product")
            .filter(product__legacy_source=LEGACY_SOURCE)
            .annotate(path_len=Length("image"))
            .filter(path_len=TRUNCATED_LEN)
            .order_by("product__slug", "position")
        )
        selected = [img for img in truncated if _dedupe_key(img) not in keys]
        protected = [img for img in truncated if _dedupe_key(img) in keys]

        # The legitimate 100-char image is the reason predicate 1 exists; show it
        # so a human can confirm by eye that it was spared.
        self.stdout.write(
            f"Rows at exactly {TRUNCATED_LEN} chars: {len(truncated)} "
            f"({len(selected)} truncated orphans, {len(protected)} still referenced by the source)"
        )
        for img in protected:
            self.stdout.write(f"  PROTECTED (key is in the source): {img.image.name}")
        for img in selected:
            self.stdout.write(f"  orphan pk={img.pk} {img.product.slug}: {img.image.name}")

        expect = options["expect"]
        if expect is not None and len(selected) != expect:
            raise CommandError(
                f"selected {len(selected)} rows but expected {expect} -- aborting without "
                f"deleting. The data changed since the analysis; re-check before proceeding."
            )

        if not selected:
            self.stdout.write(self.style.SUCCESS("Nothing to prune."))
            return

        if options["manifest"]:
            # Written BEFORE the rows go, so the objects can never become
            # unfindable garbage even if the delete step fails partway.
            manifest = Path(options["manifest"])
            manifest.write_text(
                "\n".join(img.image.name for img in selected) + "\n", encoding="utf-8"
            )
            self.stdout.write(f"Wrote {len(selected)} storage keys to {manifest}")

        if not options["apply"]:
            self.stdout.write(self.style.WARNING("DRY RUN -- nothing deleted. Re-run with --apply."))
            return

        # Rows only. `img.image.delete()` is deliberately NOT called: it would
        # remove the S3 object, and the bucket has versioning off.
        with transaction.atomic():
            deleted, _ = ProductImage.objects.filter(pk__in=[i.pk for i in selected]).delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted} ProductImage rows."))
        self.stdout.write("Storage objects were left in place -- sweep them in Plan-25/26 "
                          "once S3 bucket versioning is enabled.")
