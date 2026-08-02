"""Sync GIG's LGA coverage into `GigLga` (Plan-32a slice 2).

GIG's `/lga/active` and `/homedelivery/active` cap unfiltered responses at 50
rows and their strict validator allows exactly one query param, `StateId` — so
the sweep asks state by state. GIG's StateIds are their own numbering (sandbox
data stops by 45); the sweep runs to `STATE_ID_MAX` and simply collects what
answers. Rows are keyed by GIG's (state, LGA) spelling verbatim; matching onto
our `core.Region` happens after the write, only for rows whose `region` is
null, so a hand-fixed mapping survives every sync (see `GigLga`).

Coverage semantics, measured 2026-08-02: `/lga/active` lists LGAs GIG serves at
all; `/homedelivery/active` lists the subset whose `HomeDeliveryStatus` is true
(elsewhere, customers can only collect from a service centre — GIG dev,
confirmed). A row present in either sweep is active; `home_delivery` is true
iff it appears in the home-delivery sweep.
"""
from __future__ import annotations

import logging

from django.utils import timezone

from apps.core.models import Region
from apps.delivery.gig import client, names
from apps.delivery.models import GigLga

logger = logging.getLogger(__name__)

STATE_ID_MAX = 60  # sandbox data stops by 45; headroom for production renumbering


def _sweep(path: str) -> dict[tuple[str, str], dict]:
    """All rows a per-StateId sweep of `path` returns, keyed by (state, lga)."""
    rows: dict[tuple[str, str], dict] = {}
    for state_id in range(1, STATE_ID_MAX + 1):
        result = client.call("GET", f"{path}?StateId={state_id}")
        data = result.data.get("data", []) if isinstance(result.data, dict) else result.data
        for row in data or []:
            rows[(row["LGAState"], row["LGAName"])] = row
    return rows


def sync_gig_coverage() -> dict:
    """One full sweep of both endpoints, upserted into GigLga. Returns counts."""
    active = _sweep("/lga/active")
    home = _sweep("/homedelivery/active")
    seen = {**active, **home}
    now = timezone.now()

    existing = {(g.state_name, g.lga_name): g for g in GigLga.objects.all()}
    created = updated = 0
    for (state, lga), row in seen.items():
        fields = {
            "gig_state_id": row.get("StateId", 0),
            "is_active": True,
            "home_delivery": (state, lga) in home or bool(row.get("HomeDeliveryStatus")),
            "synced_at": now,
        }
        obj = existing.get((state, lga))
        if obj is None:
            GigLga.objects.create(state_name=state, lga_name=lga, **fields)
            created += 1
        else:
            changed = [k for k, v in fields.items() if getattr(obj, k) != v]
            if changed:
                for k in changed:
                    setattr(obj, k, fields[k])
                obj.save(update_fields=changed)
                if changed != ["synced_at"]:
                    updated += 1

    # Vanished from GIG's list -> deactivated, never deleted (mapping survives).
    # Every row seen this run carries synced_at=now, so "not now" IS the vanished set.
    deactivated = (
        GigLga.objects.filter(is_active=True).exclude(synced_at=now).update(is_active=False)
    )

    matched = _match_unmapped()
    counts = {
        "active": len(active),
        "home_delivery": len(home),
        "created": created,
        "updated": updated,
        "deactivated": deactivated,
        "newly_matched": matched,
        "unmatched": GigLga.objects.filter(region__isnull=True, is_active=True).count(),
    }
    logger.info("gig coverage sync: %s", counts)
    return counts


# Hand-verified spellings the passes below cannot reach: (state, our LGA) -> GIG's name.
_ALIASES = {
    ("federalcapitalterritory", "municipalareacouncil"): "amac",
}


def _match_unmapped() -> int:
    """Auto-match rows whose `region` is null. Never touches a set FK.

    Two passes with different sharing rules: EXACT name matches may map onto a
    region that already has a mapped row — GIG lists the same LGA under several
    spellings ("Ikpoba Okha", "Ikpoba/Okha", "ikpoba-Okha"), and if only one
    variant were mapped, that variant going inactive would wrongly drop the
    LGA's coverage while a live twin sat unmapped. FUZZY stays one-to-one and
    only fights over unclaimed regions, because "close enough" twice is how a
    street-level zone ends up attached to somebody's LGA.
    """
    unmapped = list(GigLga.objects.filter(region__isnull=True))
    if not unmapped:
        return 0
    regions = list(
        Region.objects.filter(country_code="NG", level="area").select_related("parent")
    )
    known_states = {names.norm(r.parent.name) for r in regions if r.parent}
    by_key = {(names.norm(r.parent.name), names.region_lga_key(r)): r for r in regions if r.parent}
    alias_to_db = {(state, ext): (state, ours) for (state, ours), ext in _ALIASES.items()}

    matched = 0
    leftovers = []
    for gig_lga in unmapped:
        key = (names.state_key(gig_lga.state_name, known_states), names.norm(gig_lga.lga_name))
        region = by_key.get(key) or by_key.get(alias_to_db.get(key, ("", "")))
        if region is not None:
            gig_lga.region = region
            gig_lga.save(update_fields=["region"])
            matched += 1
        else:
            leftovers.append(gig_lga)

    if leftovers:
        taken = set(
            GigLga.objects.filter(region__isnull=False).values_list("region_id", flat=True)
        )
        candidates = [r for r in regions if r.id not in taken]
        rows = [
            (names.state_key(g.state_name, known_states), names.norm(g.lga_name), g)
            for g in leftovers
        ]
        assignments, _stats = names.match_rows(rows, candidates)
        for region_id, gig_lga in assignments.items():
            gig_lga.region_id = region_id
            gig_lga.save(update_fields=["region"])
        matched += len(assignments)
    return matched
