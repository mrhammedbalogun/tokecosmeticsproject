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


def import_media(data, uploads_root, dry_run) -> tuple[int, int, list[tuple[str, str]]]:
    """Copy the ordered attachment list for every product into ProductImage rows.

    Returns (copied, missing, missing_report). missing_report is a list of
    (product_slug, relative_path) pairs -- the caller (import_catalog, which
    owns stdout) decides how to display them. This function only logs them
    via `logger.warning`.

    Ordering comes from `ordered_attachment_ids` (transform.py) -- thumbnail,
    then gallery, then ACF Small_Image_*/Medium_Image_* slots, in that
    display order -- not reimplemented here. Do NOT swap this for
    `collect_attachment_ids`: that one sorts its result, and 4 live products
    have an ACF image with a lower attachment id than their thumbnail's, which
    would put the wrong image at position 0.
    """
    uploads_root = Path(uploads_root)
    attachments: dict[str, str] = data["attachments"]
    meta_all: dict[str, dict] = data["meta"]

    products_by_wp_id = {
        p.legacy_wp_id: p for p in Product.objects.filter(legacy_source=LEGACY_SOURCE)
    }

    copied = 0
    missing = 0
    missing_report: list[tuple[str, str]] = []

    for row in data["products"]:
        wp_id = row["ID"]
        product = products_by_wp_id.get(wp_id)
        if product is None:
            continue

        product_meta = meta_all.get(str(wp_id), {})
        attachment_ids = ordered_attachment_ids(product_meta)

        existing_filenames = {Path(img.image.name).name for img in product.images.all()}

        for position, attachment_id in enumerate(attachment_ids):
            rel_path = attachments.get(str(attachment_id))
            if rel_path is None:
                # Collected as an id but never resolved to a path at all (e.g.
                # the attachment was deleted in WordPress after this id was
                # referenced). Same handling as a missing file: never fatal.
                missing += 1
                unresolved = f"<unresolved attachment id {attachment_id}>"
                logger.warning(
                    "Product %s references attachment id %s with no recorded path",
                    product.slug, attachment_id,
                )
                missing_report.append((product.slug, unresolved))
                continue

            filename = Path(rel_path).name
            if filename in existing_filenames:
                continue  # dedupe key -- re-runs are free

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

            if dry_run:
                # Count what WOULD be copied, but never touch storage.
                copied += 1
                continue

            image = ProductImage(product=product, position=position, alt=product.name)
            target_name = f"{product.slug}/{filename}"
            storage = image.image.storage
            # image.image.field.generate_filename() prepends upload_to
            # ("catalog/products/") to the name passed to .save() below --
            # replicate that here so exists()/delete() check the same path
            # the save will actually land on.
            full_target_name = image.image.field.generate_filename(image, target_name)
            # Save deterministically at the exact target path. Django's default
            # collision handling would otherwise append a random suffix when
            # something already occupies that path -- silently breaking the
            # "ends with the same filename" dedupe key this importer relies on
            # for idempotent re-runs. There is no legitimate reason for a
            # second, different file to already live at this product-scoped
            # path, so overwriting it is the correct, boring behaviour.
            if storage.exists(full_target_name):
                storage.delete(full_target_name)
            image.image.save(target_name, ContentFile(source_path.read_bytes()), save=False)
            image.save()
            existing_filenames.add(filename)
            copied += 1

    return copied, missing, missing_report
