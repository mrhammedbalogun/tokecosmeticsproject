"""Read WooCommerce and write a reviewable JSON artifact.

This is the ONLY command that opens a MariaDB connection. Credentials come from
the environment per-invocation and are never stored in .env.prod.
"""
from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.migration_wp import wp_reader

ARTIFACT_VERSION = 1


class Command(BaseCommand):
    help = "Extract the WooCommerce catalogue to a JSON artifact."

    def add_arguments(self, parser):
        parser.add_argument("--out", required=True, help="path to write the JSON artifact")

    def handle(self, *args, **options):
        out_path = Path(options["out"])

        with wp_reader.wp_connection() as conn:
            products = wp_reader.fetch_products(conn)
            product_ids = [p["ID"] for p in products]
            variations = wp_reader.fetch_variations(conn, product_ids)
            variation_ids = [v["ID"] for v in variations]
            meta = wp_reader.fetch_meta(conn, product_ids + variation_ids)
            terms = wp_reader.fetch_terms(conn)
            term_links = wp_reader.fetch_term_links(conn)

            attachment_ids = self._collect_attachment_ids(product_ids, meta)
            attachments = wp_reader.fetch_attachment_paths(conn, attachment_ids)

        out_path.parent.mkdir(parents=True, exist_ok=True)

        artifact = {
            "version": ARTIFACT_VERSION,
            "source": "wp_ng",
            "products": products,
            "variations": variations,
            "meta": {str(k): v for k, v in meta.items()},
            "terms": terms,
            "term_links": term_links,
            "attachments": {str(k): v for k, v in attachments.items()},
        }
        out_path.write_text(json.dumps(artifact, indent=2, default=str), encoding="utf-8")

        self.stdout.write(
            self.style.SUCCESS(
                f"Wrote {out_path}: {len(products)} products, {len(variations)} variations, "
                f"{len(terms)} terms, {len(attachments)} attachments"
            )
        )

    @staticmethod
    def _collect_attachment_ids(product_ids: list[int], meta: dict) -> list[int]:
        """Thumbnail + gallery + the ACF Small_Image_*/Medium_Image_* slots.

        The ACF image fields hold attachment IDs, not URLs (verified 2026-07-25).
        """
        acf_keys = [f"Small_Image_{i}" for i in range(1, 5)]
        acf_keys += [f"Medium_Image_{i}" for i in range(1, 3)]
        ids: set[int] = set()
        for pid in product_ids:
            m = meta.get(pid, {})
            if (m.get("_thumbnail_id") or "").strip().isdigit():
                ids.add(int(m["_thumbnail_id"]))
            gallery = (m.get("_product_image_gallery") or "").strip()
            for part in gallery.split(","):
                if part.strip().isdigit():
                    ids.add(int(part.strip()))
            for key in acf_keys:
                val = (m.get(key) or "").strip()
                if val.isdigit():
                    ids.add(int(val))
        return sorted(ids)
