"""Extract the legacy URL space to a JSON artifact (Plan-24).

Unlike the customer and order artifacts this one holds NO personal data — it is published
marketing copy and public URLs — so it is written with ordinary permissions and may be
kept. It is still not committed: it is a build input, not source.
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.migration_wp import wp_reader

ARTIFACT_VERSION = 1


class _ArtifactEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (datetime.datetime, datetime.date)):
            return obj.isoformat()
        return super().default(obj)


class Command(BaseCommand):
    help = "Extract legacy pages, posts, help articles and taxonomy terms to JSON."

    def add_arguments(self, parser):
        parser.add_argument("--out", required=True)

    def handle(self, *args, **options):
        out_path = Path(options["out"])
        if not out_path.parent.exists() and not out_path.parent.parent.is_dir():
            raise CommandError(f"--out path is not usable: {out_path.parent}")

        with wp_reader.wp_connection() as conn:
            space = wp_reader.fetch_url_space(conn)
            terms = wp_reader.fetch_terms(conn)

        artifact = {
            "version": ARTIFACT_VERSION,
            **space,
            "categories": [t for t in terms if t["taxonomy"] == "product_cat"],
            "tags": [t for t in terms if t["taxonomy"] == "product_tag"],
        }
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(artifact, indent=2, cls=_ArtifactEncoder), encoding="utf-8"
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Wrote {out_path}: {len(artifact['pages'])} pages, "
                f"{len(artifact['posts'])} posts, {len(artifact['helps'])} help articles, "
                f"{len(artifact['categories'])} categories, {len(artifact['tags'])} tags"
            )
        )
