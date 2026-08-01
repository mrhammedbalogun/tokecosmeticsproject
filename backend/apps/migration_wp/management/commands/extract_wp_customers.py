"""Read one WooCommerce store's customers to a JSON artifact (Plan-22).

Opens a MariaDB connection. Credentials come from the environment per-invocation, from a
root-only 0600 file on the server, and are never written to .env.prod.

── THIS ARTIFACT IS THE MOST SENSITIVE FILE THIS PROJECT PRODUCES ───────────────────────

It contains ~977 real password hashes, names, emails and phone numbers. Three consequences,
all enforced here rather than left to the runbook:

* It is written **0600**, before any content goes into it, so it is never briefly
  world-readable on a shared box.
* It must **never be committed**. Test fixtures use synthetic hashes generated locally;
  nothing in `tests/fixtures/` came from a real customer.
* It is **deleted after import** — see `docs/runbooks/migration.md`. A file of password
  hashes that outlives its purpose is a breach waiting for an unrelated mistake.

One store per invocation, because `WP_DB_NAME` and `WP_TABLE_PREFIX` are per-connection
settings. Three stores means three runs with three environments; `--store` is what labels
the artifact and must match the prefix being read, so it is checked against the
LegacyStore choices rather than accepted free-form.
"""

from __future__ import annotations

import datetime
import json
import os
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import LegacyStore
from apps.migration_wp import wp_reader

ARTIFACT_VERSION = 1


class _ArtifactEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (datetime.datetime, datetime.date)):
            return obj.isoformat()
        return super().default(obj)


class Command(BaseCommand):
    help = "Extract one WooCommerce store's customers (users with >=1 order) to JSON."

    def add_arguments(self, parser):
        parser.add_argument(
            "--store",
            required=True,
            choices=[s.value for s in LegacyStore],
            help="which store this artifact is from; becomes LegacyIdentity.store",
        )
        parser.add_argument("--out", required=True, help="path to write the JSON artifact")

    def handle(self, *args, **options):
        store = options["store"]
        out_path = Path(options["out"])
        self._validate_out_path(out_path)

        with wp_reader.wp_connection() as conn:
            customers = wp_reader.fetch_customers(conn)
            user_ids = [c["ID"] for c in customers]
            meta = wp_reader.fetch_user_meta(conn, user_ids)

        artifact = {
            "version": ARTIFACT_VERSION,
            "store": store,
            "table_prefix": settings.WP_TABLE_PREFIX,
            "customers": customers,
            "meta": {str(k): v for k, v in meta.items()},
        }

        out_path.parent.mkdir(parents=True, exist_ok=True)
        # Create the file EMPTY AND 0600 first, then write. Writing first and chmod-ing
        # after would leave a window — short, but on a box that is being actively probed —
        # in which every password hash on the store is world-readable.
        fd = os.open(out_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(artifact, fh, indent=2, cls=_ArtifactEncoder)

        self.stdout.write(
            self.style.SUCCESS(
                f"Wrote {out_path} (0600): {len(customers)} customers from {store} "
                f"(prefix {settings.WP_TABLE_PREFIX})"
            )
        )
        self.stdout.write(
            self.style.WARNING(
                "This file contains real password hashes. Do not commit it; delete it "
                "after import."
            )
        )

    @staticmethod
    def _validate_out_path(out_path: Path) -> None:
        """Fail on a bad --out before touching the live database, as extract_wp_catalog
        does. Same reasoning: a typo should cost nothing, not a full table scan against a
        box that is simultaneously serving the storefront."""
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
