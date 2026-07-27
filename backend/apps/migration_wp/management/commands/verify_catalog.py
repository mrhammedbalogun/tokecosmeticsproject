"""Post-import verification and hand-off worklists (Plan-21 Task 13).

Read-only against the database: this command never writes to Postgres. It
compares what the artifact says should exist against what import_catalog
actually wrote, flags a few specific gaps import_catalog's own summary can't
see, and writes four CSV worklists for the humans who pick this up after
the code is done.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.catalog.models import Category, Product, ProductImage, ProductVariant
from apps.migration_wp.importers.categories import tag_skip_reason
from apps.migration_wp.importers.common import LEGACY_SOURCE
from apps.migration_wp.transform import collect_attachment_ids, ordered_attachment_ids

WP_CONTENT_NEEDLE = "wp-content"


class Command(BaseCommand):
    """Verify a completed import_catalog run against its source artifact.

    Entirely read-only -- it issues no writes to Postgres. The only output
    side effects are the four CSV worklists under --out-dir.
    """

    help = "Verify an import_catalog run and write manual-worklist CSVs."

    def add_arguments(self, parser):
        parser.add_argument("artifact", help="path to catalog-export.json")
        parser.add_argument(
            "--out-dir", default="docs/migration", help="directory to write worklist CSVs into"
        )

    def handle(self, *args, **options):
        data = json.loads(Path(options["artifact"]).read_text(encoding="utf-8"))
        out_dir = Path(options["out_dir"])
        out_dir.mkdir(parents=True, exist_ok=True)

        products = list(
            Product.objects.filter(legacy_source=LEGACY_SOURCE).prefetch_related(
                "variants__prices__currency", "images"
            )
        )

        self._write_counts(data, products)
        self._write_orphans(data, products)
        self._write_wp_content_scan(products)
        self._write_unknown_weight(products)
        self._write_samples(products)

        self._write_pricing_todo(out_dir, products)
        self._write_stock_todo(out_dir)
        self._write_description_review(out_dir, products)
        self._write_tags_todo(out_dir, data)

    # --- stdout report -----------------------------------------------------

    def _write_counts(self, data, products):
        meta_all = data["meta"]
        source_products = len(data["products"])

        source_categories = len([t for t in data["terms"] if t["taxonomy"] == "product_cat"])
        # Count Category rows directly (not by walking imported products'
        # category links) -- a category with no products currently linked
        # (e.g. the fixture's orphan-cat, parentless but still imported) is
        # still a real, correctly-imported Category row. Walking product
        # links undercounts and would print a false shortfall that tells the
        # review team categories are missing when they aren't.
        dest_categories = Category.objects.filter(legacy_wp_id__isnull=False).count()

        variations_by_parent = {}
        for v in data["variations"]:
            variations_by_parent.setdefault(v["post_parent"], []).append(v)
        source_variants = sum(
            len(variations_by_parent.get(row["ID"], [])) or 1 for row in data["products"]
        )
        dest_variants = ProductVariant.objects.filter(product__legacy_source=LEGACY_SOURCE).count()

        source_prices = 0
        for row in data["products"]:
            children = variations_by_parent.get(row["ID"], [])
            metas = (
                [meta_all.get(str(c["ID"]), {}) for c in children]
                if children
                else [meta_all.get(str(row["ID"]), {})]
            )
            for m in metas:
                if (m.get("_regular_price") or "").strip():
                    source_prices += 1
                if (m.get("_sale_price") or "").strip():
                    source_prices += 1
        dest_prices = sum(v.prices.count() for p in products for v in p.variants.all())

        source_images = 0
        attachments = data["attachments"]
        for row in data["products"]:
            ids = collect_attachment_ids([row["ID"]], {row["ID"]: meta_all.get(str(row["ID"]), {})})
            source_images += sum(1 for i in ids if str(i) in attachments)
        dest_images = ProductImage.objects.filter(product__legacy_source=LEGACY_SOURCE).count()

        self.stdout.write("Counts (source -> dest):")
        self.stdout.write(f"  products:   {source_products} -> {len(products)}")
        self.stdout.write(f"  categories: {source_categories} -> {dest_categories}")
        self.stdout.write(f"  variants:   {source_variants} -> {dest_variants}")
        self.stdout.write(f"  prices:     {source_prices} -> {dest_prices}")
        self.stdout.write(f"  images:     {source_images} -> {dest_images}")

    def _write_orphans(self, data, products):
        source_wp_ids = {row["ID"] for row in data["products"]}
        orphan_products = [p for p in products if p.legacy_wp_id not in source_wp_ids]
        self.stdout.write(f"Orphans (in Postgres, not in artifact): {len(orphan_products)}")
        if orphan_products:
            self.stdout.write(
                "  update_or_create never deletes -- these products were removed "
                "from WordPress since the last import and must be handled by hand "
                "(unpublish/archive), the importer will never do it for you:"
            )
            for p in orphan_products:
                self.stdout.write(f"    - {p.slug} (legacy_wp_id={p.legacy_wp_id})")

        orphan_images = self._orphan_images(data, products)
        self.stdout.write(
            f"Orphan images (no longer referenced by the source): {len(orphan_images)}"
        )
        if orphan_images:
            self.stdout.write(
                "  never deleted -- ProductImage has no provenance marker to tell a "
                "stale source image apart from a staff upload, so import_media only "
                "pushes these after the current source-backed images each run; a "
                "human still has to decide whether to remove them:"
            )
            for slug, filename in orphan_images:
                self.stdout.write(f"    - {slug}: {filename}")

    def _orphan_images(self, data, products):
        """Mirrors import_media's own orphan check (read-only here): a
        ProductImage whose <attachment_id>-<filename> key no longer matches
        anything the current artifact resolves for that product.
        """
        meta_all = data["meta"]
        attachments = data["attachments"]
        orphans = []
        for p in products:
            product_meta = meta_all.get(str(p.legacy_wp_id), {})
            current_keys = set()
            for attachment_id in ordered_attachment_ids(product_meta):
                rel_path = attachments.get(str(attachment_id))
                if rel_path is None:
                    continue
                current_keys.add(f"{attachment_id}-{Path(rel_path).name}")
            for img in p.images.all():
                key = Path(img.image.name).name
                if key not in current_keys:
                    orphans.append((p.slug, key))
        return orphans

    def _write_wp_content_scan(self, products):
        hits = [
            p
            for p in products
            if WP_CONTENT_NEEDLE in (p.description or "") or WP_CONTENT_NEEDLE in (p.short_description or "")
        ]
        self.stdout.write(f"wp-content URL scan: {len(hits)} product(s) with a wp-content reference")
        if hits:
            self.stdout.write(
                "  these would 404 the moment DNS moves off the old server -- fix before cutover:"
            )
            for p in hits:
                self.stdout.write(f"    - {p.slug}")

    def _write_unknown_weight(self, products):
        variant_ids = [v.pk for p in products for v in p.variants.all()]
        unknown = ProductVariant.objects.filter(pk__in=variant_ids, weight_grams__isnull=True).count()
        self.stdout.write(
            f"Unknown weight (weight_grams IS NULL): {unknown} variant(s) -- "
            "apps/delivery/services.py:42 treats an unknown weight as 0g, silently "
            "undercharging shipping until a real weight is entered."
        )

    def _write_samples(self, products):
        self.stdout.write("Sample products:")
        for p in sorted(products, key=lambda p: p.name)[:5]:
            variants = list(p.variants.all())
            base_price = None
            default = next((v for v in variants if v.is_default), variants[0] if variants else None)
            if default is not None:
                base = next(
                    (
                        pr
                        for pr in default.prices.all()
                        if pr.currency_id == "NGN" and pr.country_id is None and pr.starts_at is None
                    ),
                    None,
                )
                base_price = base.amount if base else None
            self.stdout.write(
                f"  - {p.name} ({p.slug}): base_price={base_price} "
                f"variants={len(variants)} images={p.images.count()}"
            )

    # --- CSV worklists -------------------------------------------------------

    def _write_pricing_todo(self, out_dir, products):
        # utf-8-sig (not plain utf-8): these CSVs are handed to a non-developer
        # team to open in Excel, which mojibakes accented product names
        # without a BOM. Matches the convention already established by
        # apps/catalog/csv_io.py and apps/inventory/csv_io.py.
        path = out_dir / "pricing-todo.csv"
        with path.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["sku", "product", "ngn_price", "gbp", "usd", "cad"])
            # Explicit order (not Product.Meta's newest-first) -- someone
            # scanning this sheet by eye needs to find a product by name.
            for p in sorted(products, key=lambda p: p.name):
                for v in sorted(p.variants.all(), key=lambda v: v.sku):
                    ngn = next(
                        (
                            pr.amount
                            for pr in v.prices.all()
                            if pr.currency_id == "NGN" and pr.country_id is None and pr.starts_at is None
                        ),
                        "",
                    )
                    writer.writerow([v.sku, p.name, ngn, "", "", ""])

    def _write_stock_todo(self, out_dir):
        from apps.inventory.models import StockItem

        path = out_dir / "stock-todo.csv"
        with path.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["sku", "product", "warehouse", "seeded_qty", "real_qty"])
            items = (
                StockItem.objects.select_related("variant", "variant__product", "warehouse")
                .filter(variant__product__legacy_source=LEGACY_SOURCE)
                .order_by("variant__product__name", "variant__sku")
            )
            for item in items:
                writer.writerow(
                    [item.variant.sku, item.variant.product.name, item.warehouse.name, item.quantity, ""]
                )

    def _write_tags_todo(self, out_dir, data):
        """Every product_tag the import refused, and which products wanted it.

        Recomputed from the artifact with the importer's own predicate rather
        than passed across from import_catalog, so this stays correct when
        verify_catalog is run on its own -- and so there is exactly one
        definition of what counts as a junk tag.
        """
        titles = {p["ID"]: p["post_title"] for p in data["products"]}
        products_for_term: dict[int, list[str]] = {}
        for link in data.get("term_links") or []:
            if link.get("taxonomy") != "product_tag":
                continue
            name = titles.get(link["object_id"])
            if name:
                products_for_term.setdefault(link["term_id"], []).append(name)

        rows = []
        for term in data["terms"]:
            if term["taxonomy"] != "product_tag":
                continue
            reason = tag_skip_reason(term)
            if reason:
                rows.append((term, reason, products_for_term.get(term["term_id"], [])))

        path = out_dir / "tags-todo.csv"
        with path.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["wp_term_id", "reason", "products", "original_tag_text"])
            for term, reason, names in sorted(rows, key=lambda r: r[0]["name"]):
                writer.writerow(
                    [term["term_id"], reason, "; ".join(sorted(names)), term["name"]]
                )
        self.stdout.write(f"skipped tags: {len(rows)} (see {path.name})")

    def _write_description_review(self, out_dir, products):
        path = out_dir / "description-review.csv"
        with path.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(
                ["slug", "product", "description_chars", "ingredients", "directions", "warnings"]
            )
            for p in sorted(products, key=lambda p: p.name):
                writer.writerow(
                    [
                        p.slug,
                        p.name,
                        len(p.description or ""),
                        "OK" if (p.ingredients or "").strip() else "MISSING",
                        "OK" if (p.directions or "").strip() else "MISSING",
                        "OK" if (p.warnings or "").strip() else "MISSING",
                    ]
                )
