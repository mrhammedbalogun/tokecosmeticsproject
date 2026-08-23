"""Our NG state regions -> AAJ's `stateOrProvinceCode` (Plan-43).

THIS TABLE IS LOAD-BEARING FOR MONEY. Measured on the sandbox 2026-08-23: the code
is the ONLY receiver field AAJ prices by (the state name and the city string are
ignored for pricing), and an UNKNOWN code does not error — it silently prices as
Lagos (₦2,779 where Kano is ₦9,099). A typo here would undercharge every customer
in that state by the difference, on every order, with no signal. Hence: an explicit
37-row table keyed on our seeded `core.Region` names (fixtures/ng_regions.json),
and `state_code()` returns None for anything not in it so the caller OMITS the
option rather than guessing.

Codes are AAJ's own, from their delivery-locations endpoint (`stateCode`), which is
the runtime source of truth; their docs list FCT as "FC" and the endpoint as "FCT" —
both price identically (measured), and the endpoint's spelling is used.
"""
from __future__ import annotations

STATE_CODES: dict[str, str] = {
    "Abia": "AB",
    "Adamawa": "AD",
    "Akwa Ibom": "AK",
    "Anambra": "AN",
    "Bauchi": "BA",
    "Bayelsa": "BY",
    "Benue": "BE",
    "Borno": "BO",
    "Cross River": "CR",
    "Delta": "DE",
    "Ebonyi": "EB",
    "Edo": "ED",
    "Ekiti": "EK",
    "Enugu": "EN",
    "Federal Capital Territory": "FCT",
    "Gombe": "GO",
    "Imo": "IM",
    "Jigawa": "JI",
    "Kaduna": "KA",
    "Kano": "KN",
    "Katsina": "KT",
    "Kebbi": "KE",
    "Kogi": "KO",
    "Kwara": "KW",
    "Lagos": "LA",
    "Nasarawa": "NA",
    "Niger": "NI",
    "Ogun": "OG",
    "Ondo": "ON",
    "Osun": "OS",
    "Oyo": "OY",
    "Plateau": "PL",
    "Rivers": "RI",
    "Sokoto": "SO",
    "Taraba": "TA",
    "Yobe": "YO",
    "Zamfara": "ZA",
}

# Spellings other sources use for the same state (AAJ's list says "Nassarawa" and
# "Fct"; a SenderLocation's free-text `state` may say "Abuja"). Keys are normalised
# by `_norm`.
_ALIASES = {
    "fct": "Federal Capital Territory",
    "abuja": "Federal Capital Territory",
    "abujafct": "Federal Capital Territory",
    "federalcapitalterritory": "Federal Capital Territory",
    "nassarawa": "Nasarawa",
    "crossriver": "Cross River",
    "akwaibom": "Akwa Ibom",
}


def _norm(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


def canonical_state(name: str | None) -> str | None:
    """Our seeded state name for an external/free-text spelling, or None."""
    if not name:
        return None
    n = _norm(name)
    if n.endswith("state") and len(n) > 5:
        n = n[:-5]
    if n in _ALIASES:
        return _ALIASES[n]
    for canonical in STATE_CODES:
        if _norm(canonical) == n:
            return canonical
    return None


def state_code(name: str | None) -> str | None:
    """AAJ's code for a state name (ours or a known alias), or None — never a guess."""
    canonical = canonical_state(name)
    return STATE_CODES.get(canonical) if canonical else None
