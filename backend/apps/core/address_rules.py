"""Per-country required-field rules for the structured Address.

One place decides which address fields are mandatory per country, so the serializer
(Plan-11) and any admin form share a single source of truth.

Two independent axes, NOT an either/or:
- Does the country have a seeded Region tree? -> `state_region` is required (the
  delivery matcher works on region FKs; free text never matches a region-scoped
  option). NG at launch; GB/US/CA since the Countries_breakdown work.
- Does the country address with free text and a postcode? GB/US/CA need BOTH a
  structured state AND city + postcode — the postcode is what actually routes a
  GB/US parcel, so joining REGION_COUNTRIES must never cost a country its
  postcode requirement.
"""

# Countries with a seeded Region tree -> the state/province/constituent-country
# dropdown is required. NG additionally requires area_region (the LGA) when the
# chosen state has children — enforced on NEW addresses in
# AddressSerializer.validate, which can see the chosen state.
REGION_COUNTRIES = {"NG", "GB", "US", "CA"}

# Countries where the city is a free-text field (everywhere except NG, where the
# LGA dropdown plays that role).
_CITY_TEXT_EXEMPT = {"NG"}

# Base requirement for every address.
_BASE = {"line1", "country_code", "first_name", "phone"}

# Countries where a postcode is mandatory.
_POSTCODE_COUNTRIES = {"GB", "US", "CA"}


def required_fields_for(country_code: str) -> set[str]:
    country_code = (country_code or "").upper()
    fields = set(_BASE)
    if country_code in REGION_COUNTRIES:
        fields.add("state_region")
    if country_code not in _CITY_TEXT_EXEMPT:
        fields.add("city_text")
    if country_code in _POSTCODE_COUNTRIES:
        fields.add("postcode")
    return fields
