"""Load Nigerian LGA centre-points onto `core.Region` from the bundled dataset.

Dataset: `apps/delivery/data/ng_lga_centroids.csv`, extracted from the GeoNames
gazetteer (download.geonames.org/export/dump/NG.zip, feature ADM2, CC-BY 4.0),
785 rows against our 774 seeded LGAs.

Matching is exact on normalized (state, lga) first, then a same-state fuzzy pass
(difflib, cutoff 0.85) for GeoNames spelling variants ("Fufore" vs "Fufure",
"Makurdi Local Government Area" vs "Makurdi"). Whatever survives both passes is
printed, not guessed at — an LGA without a centroid never offers GIG, which is a
worse outcome than a blank line in this command's output only if nobody reads
the output.
"""
from __future__ import annotations

import csv
import re
from difflib import get_close_matches
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.core.models import Region

DATA = Path(__file__).resolve().parents[2] / "data" / "ng_lga_centroids.csv"

# Normalized-name suffixes GeoNames sometimes appends to an LGA's proper name.
_SUFFIXES = ("localgovernmentarea", "localgovtarea", "lga")
# 0.82 admits the real spelling variants ("fufore"/"fufure" scores 0.833) while the
# two-pass structure below keeps fuzzy from ever out-competing an exact row.
FUZZY_CUTOFF = 0.82

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


def _norm(name: str) -> str:
    n = re.sub(r"[^a-z0-9]", "", name.lower())
    for suffix in _SUFFIXES:
        if n.endswith(suffix) and len(n) > len(suffix):
            n = n[: -len(suffix)]
    return n


def _state_key(name: str, known_states: set[str]) -> str:
    n = _norm(name)
    if n.endswith("state") and n[:-5] in known_states:
        return n[:-5]
    return n


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
        states = {_norm(r.parent.name) for r in regions if r.parent}

        def region_lga_key(region: Region) -> str:
            """Our seed disambiguates duplicate LGA names with a trailing
            "<State> State" ("Surulere Lagos State", "Ekiti Kwara State") — strip
            that form ONLY. Never the bare state name: real LGAs end with it
            (Oredo/Edo, Birnin Kebbi/Kebbi, Unuimo/Imo)."""
            n = _norm(region.name)
            tail = _norm(region.parent.name) + "state"
            if n.endswith(tail) and len(n) > len(tail):
                return n[: -len(tail)]
            return n

        by_key = {(_norm(r.parent.name), region_lga_key(r)): r for r in regions if r.parent}
        lgas_per_state: dict[str, dict[str, Region]] = {}
        for (state, lga), region in by_key.items():
            lgas_per_state.setdefault(state, {})[lga] = region

        with DATA.open(encoding="utf-8") as f:
            rows = [
                (_state_key(r["state"], states), _norm(r["lga"]), r)
                for r in csv.DictReader(f)
            ]

        # Pass 1: exact keys claim their region. Pass 2: leftover rows fuzzy-match
        # against still-unclaimed regions only, so a spelling-variant guess can never
        # out-compete an exact row that appears later in the file.
        # A CSV row also answers to an aliased DB name: (state, csv name) -> DB key.
        csv_to_db_key = {
            (state, csv_name): (state, our_name) for (state, our_name), csv_name in _ALIASES.items()
        }

        assignments: dict[int, dict] = {}  # region id -> csv row
        exact = fuzzy = skipped = 0
        leftovers = []
        for state, lga, row in rows:
            region = by_key.get((state, lga)) or by_key.get(csv_to_db_key.get((state, lga), ("", "")))
            if region is not None and region.id not in assignments:
                assignments[region.id] = row
                exact += 1
            else:
                leftovers.append((state, lga, row))
        for state, lga, row in leftovers:
            unclaimed = {
                name: region
                for name, region in lgas_per_state.get(state, {}).items()
                if region.id not in assignments
            }
            close = get_close_matches(lga, unclaimed.keys(), n=1, cutoff=FUZZY_CUTOFF)
            if close:
                assignments[unclaimed[close[0]].id] = row
                fuzzy += 1

        touched: list[Region] = []
        matched_ids = set(assignments)
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

        unmatched = [r for r in regions if r.id not in matched_ids]
        self.stdout.write(
            f"exact {exact}, fuzzy {fuzzy}, updated {len(touched)}, "
            f"already-set skipped {skipped}, LGAs without a centroid: {len(unmatched)}"
        )
        for r in sorted(unmatched, key=lambda r: (r.parent.name, r.name)):
            self.stdout.write(f"  NO CENTROID: {r.parent.name} / {r.name}")
