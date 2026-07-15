"""Per-country required-field rules for the structured Address.

One place decides which address fields are mandatory per country, so the serializer
(Plan-11) and any admin form share a single source of truth.
- Countries WITH seeded regions (NG at launch) require the structured region link.
- Countries WITHOUT region data use free text + postcode.
"""

# Countries that have (or will have) a seeded Region tree → use dropdowns.
REGION_COUNTRIES = {"NG"}

# Base requirement for every address.
_BASE = {"line1", "country_code", "first_name", "phone"}

# Countries where a postcode is mandatory.
_POSTCODE_COUNTRIES = {"GB", "US", "CA"}


def required_fields_for(country_code: str) -> set[str]:
    country_code = (country_code or "").upper()
    fields = set(_BASE)
    if country_code in REGION_COUNTRIES:
        # State/region chosen from the tree; LGA (area_region) enforced by the
        # serializer only when the chosen state has children (Plan-11).
        fields.add("state_region")
    else:
        fields.add("city_text")
        if country_code in _POSTCODE_COUNTRIES:
            fields.add("postcode")
    return fields
