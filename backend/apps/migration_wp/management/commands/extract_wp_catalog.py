"""Read WooCommerce and write a reviewable JSON artifact.

This is the ONLY command that opens a MariaDB connection. Credentials come from
the environment per-invocation and are never stored in .env.prod.
"""
from __future__ import annotations

import datetime
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.migration_wp import wp_reader
from apps.migration_wp.transform import collect_attachment_ids

ARTIFACT_VERSION = 1


class _ArtifactEncoder(json.JSONEncoder):
    """The only non-JSON-native type this artifact ever carries is the
    datetime that comes back from `post_date_gmt`. Anything else that isn't
    natively serializable should raise loudly — silently stringifying an
    unexpected type is exactly the kind of quiet corruption a migration
    artifact must not tolerate.
    """

    def default(self, obj):
        if isinstance(obj, (datetime.datetime, datetime.date)):
            return obj.isoformat()
        return super().default(obj)


class Command(BaseCommand):
    help = "Extract the WooCommerce catalogue to a JSON artifact."

    def add_arguments(self, parser):
        parser.add_argument("--out", required=True, help="path to write the JSON artifact")

    def handle(self, *args, **options):
        out_path = Path(options["out"])
        self._validate_out_path(out_path)

        with wp_reader.wp_connection() as conn:
            products = wp_reader.fetch_products(conn)
            product_ids = [p["ID"] for p in products]
            variations = wp_reader.fetch_variations(conn, product_ids)
            variation_ids = [v["ID"] for v in variations]
            meta = wp_reader.fetch_meta(conn, product_ids + variation_ids)
            terms = wp_reader.fetch_terms(conn)
            term_links = wp_reader.fetch_term_links(conn)

            attachment_ids = collect_attachment_ids(product_ids, meta)
            attachments = wp_reader.fetch_attachment_paths(conn, attachment_ids)

        missing_attachments = sorted(set(attachment_ids) - set(attachments.keys()))

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
            "missing_attachments": missing_attachments,
        }
        out_path.write_text(json.dumps(artifact, indent=2, cls=_ArtifactEncoder), encoding="utf-8")

        self.stdout.write(
            self.style.SUCCESS(
                f"Wrote {out_path}: {len(products)} products, {len(variations)} variations, "
                f"{len(terms)} terms, {len(attachments)} attachments"
                + (f", {len(missing_attachments)} missing attachments" if missing_attachments else "")
            )
        )

    @staticmethod
    def _validate_out_path(out_path: Path) -> None:
        """Fail before touching the live DB if --out can't possibly be written.

        Walks up to the nearest existing ancestor of the target path and
        confirms it's a directory, without creating anything — the actual
        `mkdir` only happens after a successful extract (see handle()), so a
        failed run never leaves stray directories or partial artifacts
        behind. This just moves a *typo in --out* from "discovered after
        querying the whole production catalogue" to "discovered immediately."
        """
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
