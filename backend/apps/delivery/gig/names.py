"""Matching external Nigerian place names onto our seeded `core.Region` rows.

Shared by the centroid loader (GeoNames spellings) and the GIG coverage sync
(GIG's own LGA list). Both sources disagree with our seed in the same ways:
punctuation/spacing ("Amuwo-Odofin"/"Amuwo Odofin"), appended qualifiers
("Makurdi Local Government Area"), state-name forms ("Lagos State"/"Lagos",
"FCT"/"Federal Capital Territory"), and one-letter spelling drift
("Fufore"/"Fufure").

The matcher is two-pass: exact keys claim regions first, then fuzzy fights only
over what exact left unclaimed — so a spelling-variant guess can never
out-compete an exact row that appears later in the input.
"""
from __future__ import annotations

import re
from difflib import get_close_matches

# 0.82 admits the real spelling variants ("fufore"/"fufure" scores 0.833) while the
# two-pass structure keeps fuzzy from ever out-competing an exact match.
FUZZY_CUTOFF = 0.82

# Normalized suffixes external sources sometimes append to an LGA's proper name.
_LGA_SUFFIXES = ("localgovernmentarea", "localgovtarea", "lga")

# External state spellings -> our normalized state name.
STATE_ALIASES = {
    "fct": "federalcapitalterritory",
    "abuja": "federalcapitalterritory",
    "abujafct": "federalcapitalterritory",
    "nassarawa": "nasarawa",
}


def norm(name: str) -> str:
    n = re.sub(r"[^a-z0-9]", "", name.lower())
    for suffix in _LGA_SUFFIXES:
        if n.endswith(suffix) and len(n) > len(suffix):
            n = n[: -len(suffix)]
    return n


def state_key(name: str, known_states: set[str]) -> str:
    """Normalize an external state name: alias it, then strip a trailing "state"
    when the remainder is a state we know ("Lagos State" -> "lagos")."""
    n = norm(name)
    n = STATE_ALIASES.get(n, n)
    if n.endswith("state") and n[:-5] in known_states:
        n = n[:-5]
    return STATE_ALIASES.get(n, n)


def region_lga_key(region) -> str:
    """Our seed disambiguates duplicate LGA names with a trailing "<State> State"
    ("Surulere Lagos State", "Ekiti Kwara State") — strip that form ONLY. Never
    the bare state name: real LGAs end with it (Oredo/Edo, Birnin Kebbi/Kebbi,
    Unuimo/Imo)."""
    n = norm(region.name)
    tail = norm(region.parent.name) + "state"
    if n.endswith(tail) and len(n) > len(tail):
        return n[: -len(tail)]
    return n


def match_rows(rows, regions, aliases=None):
    """Two-pass match of external rows onto area Regions.

    `rows`: iterable of (state_key, lga_key, payload) — already normalized.
    `regions`: NG area Regions with parents loaded.
    `aliases`: {(state, our_lga): external_lga} hand-verified pairs.

    Returns ({region_id: payload}, {"exact": n, "fuzzy": m}); a payload matches
    at most one region and vice versa.
    """
    by_key = {(norm(r.parent.name), region_lga_key(r)): r for r in regions if r.parent}
    lgas_per_state: dict[str, dict[str, object]] = {}
    for (state, lga), region in by_key.items():
        lgas_per_state.setdefault(state, {})[lga] = region
    external_to_db = {
        (state, ext_name): (state, our_name)
        for (state, our_name), ext_name in (aliases or {}).items()
    }

    assignments: dict[int, object] = {}
    stats = {"exact": 0, "fuzzy": 0}
    leftovers = []
    for state, lga, payload in rows:
        region = by_key.get((state, lga)) or by_key.get(external_to_db.get((state, lga), ("", "")))
        if region is not None and region.id not in assignments:
            assignments[region.id] = payload
            stats["exact"] += 1
        else:
            leftovers.append((state, lga, payload))
    for state, lga, payload in leftovers:
        unclaimed = {
            name: region
            for name, region in lgas_per_state.get(state, {}).items()
            if region.id not in assignments
        }
        close = get_close_matches(lga, unclaimed.keys(), n=1, cutoff=FUZZY_CUTOFF)
        if close:
            assignments[unclaimed[close[0]].id] = payload
            stats["fuzzy"] += 1
    return assignments, stats
