"""Load Nigerian LGA centre-points onto `core.Region` from the bundled dataset.

Dataset: `apps/delivery/data/ng_lga_centroids.csv`, extracted from the GeoNames
gazetteer (download.geonames.org/export/dump/NG.zip, feature ADM2, CC-BY 4.0),
785 rows against our 774 seeded LGAs.

Matching is `gig.names.match_rows` — exact first, fuzzy over the leftovers,
plus the hand-verified aliases below. Whatever survives both passes is printed,
not guessed at: an LGA without a centroid never offers GIG, which is a worse
outcome than a blank line in this command's output only if nobody reads the
output.
"""
from __future__ import annotations

import csv
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.core.models import Region
from apps.delivery.gig import names

DATA = Path(__file__).resolve().parents[2] / "data" / "ng_lga_centroids.csv"

# Hand-verified pairs the fuzzy pass cannot safely reach: normalized (state, our LGA)
# -> normalized GeoNames name. Each was checked against the LGA's real location.
# "Kuban" is a GeoNames typo for Kubau (coords land in NE Kaduna, correctly);
# "Oyo": our seed's 33 Oyo-state rows include "Oyo East" and a plain "Oyo" but no
# "Oyo West" — the plain row IS Oyo West under a shortened name, so it takes Oyo
# West's centroid.
_ALIASES = {
    ("abia", "osisioma"): "osisiomangwa",
    ("adamawa", "gayuk"): "guyuk",
    ("adamawa", "grie"): "girei",
    ("kaduna", "kubau"): "kuban",
    ("niger", "moya"): "muya",
    ("oyo", "oyo"): "oyowest",
}


class Command(BaseCommand):
    help = "Load LGA centroids from the bundled GeoNames extract onto core.Region."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Overwrite centroids that are already set (default: fill nulls only).",
        )

    def handle(self, *args, force: bool = False, **options):
        regions = list(
            Region.objects.filter(country_code="NG", level="area").select_related("parent")
        )
        known_states = {names.norm(r.parent.name) for r in regions if r.parent}

        with DATA.open(encoding="utf-8") as f:
            rows = [
                (names.state_key(r["state"], known_states), names.norm(r["lga"]), r)
                for r in csv.DictReader(f)
            ]

        assignments, stats = names.match_rows(rows, regions, aliases=_ALIASES)

        touched: list[Region] = []
        skipped = 0
        by_id = {r.id: r for r in regions}
        for region_id, row in assignments.items():
            region = by_id[region_id]
            if region.latitude is not None and not force:
                skipped += 1
                continue
            region.latitude = row["latitude"]
            region.longitude = row["longitude"]
            touched.append(region)

        Region.objects.bulk_update(touched, ["latitude", "longitude"], batch_size=200)

        unmatched = [r for r in regions if r.id not in assignments]
        self.stdout.write(
            f"exact {stats['exact']}, fuzzy {stats['fuzzy']}, updated {len(touched)}, "
            f"already-set skipped {skipped}, LGAs without a centroid: {len(unmatched)}"
        )
        for r in sorted(unmatched, key=lambda r: (r.parent.name, r.name)):
            self.stdout.write(f"  NO CENTROID: {r.parent.name} / {r.name}")
