"""Product image import phase (Plan-21 Task 12).

Copies each product's thumbnail, gallery and ACF Small_Image_*/Medium_Image_*
attachments out of the read-only wp-content/uploads mount and into
ProductImage rows, whose `image` field is backed by Django storage (S3 in
prod, local filesystem in dev/test -- see config/settings/base.py STORAGES).

THE DRY-RUN CONTRACT: `--dry-run` rolls the database back via
transaction.set_rollback, but that does not (and cannot) undo a file already
written to S3 or local disk. This importer therefore does every bit of
lookup, dedupe-checking and missing-file accounting under dry_run exactly as
it would for real, and gates ONLY the actual write -- the `image.save(...)`
call -- behind `if dry_run`. Never move that check; it is the whole guarantee
the store owner relies on when reviewing a dry run before a real cutover.
"""
from __future__ import annotations

from pathlib import Path

from django.core.files.base import ContentFile

from apps.catalog.models import Product, ProductImage
from apps.migration_wp.transform import ordered_attachment_ids

from .common import LEGACY_SOURCE, logger


def _dedupe_key(image: ProductImage) -> str:
    """The exact identity key a stored ProductImage was saved under.

    Matches the `<attachment_id>-<filename>` name `import_media` saves new
    files under (see below) -- NOT a bare filename. Two different attachments
    that happen to share a filename (ordinary in WordPress -- e.g. two
    different upload months both containing an "IMG_1234.jpg") must be
    treated as genuinely different images, so the key has to be exact rather
    than a filename heuristic.
    """
    return Path(image.image.name).name


def import_media(data, uploads_root, dry_run) -> tuple[int, int, int, list[tuple[str, str]]]:
    """Copy the ordered attachment list for every product into ProductImage rows.

    Returns (copied, missing, orphan_images, missing_report). missing_report
    is a list of (product_slug, relative_path) pairs -- the caller
    (import_catalog, which owns stdout) decides how to display them. This
    function only logs them via `logger.warning`.

    Ordering comes from `ordered_attachment_ids` (transform.py) -- thumbnail,
    then gallery, then ACF Small_Image_*/Medium_Image_* slots, in that
    display order -- not reimplemented here. Do NOT swap this for
    `collect_attachment_ids`: that one sorts its result, and 4 live products
    have an ACF image with a lower attachment id than their thumbnail's, which
    would put the wrong image at position 0.

    ORPHANED IMAGES (a product's image no longer referenced by the source --
    e.g. a gallery entry was removed in WordPress since the last run): never
    deleted. ProductImage carries no provenance marker, so deleting anything
    not currently in the source would just as happily destroy an image a
    staff member uploaded by hand through the admin -- the same clobber
    hazard as stock (see stock.py). Instead, every run re-numbers each
    product's images from scratch: source-backed images get positions
    0..N-1 in display order (so the main product photo is ALWAYS position 0,
    regardless of what happened on a previous run), and anything orphaned is
    pushed to a position after them and counted in `orphan_images` so it
    surfaces in the import summary and verify_catalog, the same way orphan
    categories/variants already do.
    """
    uploads_root = Path(uploads_root)
    attachments: dict[str, str] = data["attachments"]
    meta_all: dict[str, dict] = data["meta"]

    products_by_wp_id = {
        p.legacy_wp_id: p for p in Product.objects.filter(legacy_source=LEGACY_SOURCE)
    }

    copied = 0
    missing = 0
    orphan_images = 0
    missing_report: list[tuple[str, str]] = []

    for row in data["products"]:
        wp_id = row["ID"]
        product = products_by_wp_id.get(wp_id)
        if product is None:
            continue

        product_meta = meta_all.get(str(wp_id), {})
        attachment_ids = ordered_attachment_ids(product_meta)

        existing_images = list(product.images.all())
        existing_by_key = {_dedupe_key(img): img for img in existing_images}

        # Resolve this run's source attachments to files, in display order,
        # skipping (and counting as missing) anything that doesn't resolve --
        # never fatal, a broken image must not stop the migration.
        resolved: list[tuple[str, int, str, Path]] = []  # (key, attachment_id, filename, source_path)
        for attachment_id in attachment_ids:
            rel_path = attachments.get(str(attachment_id))
            if rel_path is None:
                # Collected as an id but never resolved to a path at all (e.g.
                # the attachment was deleted in WordPress after this id was
                # referenced). Same handling as a missing file: never fatal.
                missing += 1
                logger.warning(
                    "Product %s references attachment id %s with no recorded path",
                    product.slug, attachment_id,
                )
                missing_report.append(
                    (product.slug, f"<unresolved attachment id {attachment_id}>")
                )
                continue

            filename = Path(rel_path).name
            source_path = uploads_root / rel_path
            if not source_path.exists():
                missing += 1
                logger.warning(
                    "Missing source image for product %s: %s (attachment id %s, "
                    "uploads_root=%s)",
                    product.slug, rel_path, attachment_id, uploads_root,
                )
                missing_report.append((product.slug, rel_path))
                continue

            key = f"{attachment_id}-{filename}"
            resolved.append((key, attachment_id, filename, source_path))

        # Build the final, source-backed image list in display order, reusing
        # an existing row when its exact key already matches (dedupe --
        # re-runs are free) and otherwise copying a new one.
        source_backed: list[ProductImage] = []
        current_keys: set[str] = set()
        for key, attachment_id, filename, source_path in resolved:
            current_keys.add(key)
            existing = existing_by_key.get(key)
            if existing is not None:
                source_backed.append(existing)
                continue

            if dry_run:
                # Count what WOULD be copied, but never touch storage.
                copied += 1
                continue

            image = ProductImage(product=product, alt=product.name)
            target_name = f"{product.slug}/{key}"
            storage = image.image.storage
            # image.image.field.generate_filename() prepends upload_to
            # ("catalog/products/") to the name passed to .save() below --
            # replicate that here so exists()/delete() check the same path
            # the save will actually land on.
            full_target_name = image.image.field.generate_filename(image, target_name)
            # Save deterministically at the exact target path. Django's default
            # collision handling would otherwise append a random suffix when
            # something already occupies that path -- silently breaking this
            # importer's dedupe key on idempotent re-runs. There is no
            # legitimate reason for a second, different file to already live
            # at this product-scoped path, so overwriting it is the correct,
            # boring behaviour.
            if storage.exists(full_target_name):
                storage.delete(full_target_name)
            image.image.save(target_name, ContentFile(source_path.read_bytes()), save=False)
            image.save()
            source_backed.append(image)
            copied += 1

        # Orphans: existing rows whose key no longer matches any attachment
        # this run resolved. Left in place, never deleted, pushed after the
        # source-backed images.
        orphans = [img for img in existing_images if _dedupe_key(img) not in current_keys]
        for img in orphans:
            orphan_images += 1
            logger.warning(
                "Orphaned image for product %s: %s is no longer referenced by "
                "the source -- left in place (not deleted, no provenance "
                "marker to safely tell it apart from a staff upload) but "
                "pushed after the current images",
                product.slug, _dedupe_key(img),
            )

        # Re-number: source-backed images contiguous from 0 in display order
        # (so the main product photo is always position 0), orphans after.
        # This is an ordinary ORM write, covered by the same transaction
        # rollback as every other phase under --dry-run -- it only touches
        # rows that already exist (or were just created above), never
        # storage, so it's safe to run unconditionally.
        for position, img in enumerate(source_backed + orphans):
            if img.position != position:
                img.position = position
                img.save(update_fields=["position"])

    return copied, missing, orphan_images, missing_report
