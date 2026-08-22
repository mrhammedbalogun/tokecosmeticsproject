"""Store-locator queries and rules. The views are thin; this is where the feature is.

Three jobs live here:

1. **The public place cascade** — which countries/states/areas actually HAVE a
   store, so the customer's dropdowns can never offer a dead end.
2. **Slug resolution** — turning `/find-stores?country=ng&state=lagos` into real
   `Country`/`Region` rows without ever putting a database id in a public URL.
3. **Duplicate detection** — the soft warning the admin form shows before it lets
   somebody type the same shop in twice.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote, urlencode

from django.db.models import Case, Exists, IntegerField, OuterRef, Q, QuerySet, Value, When

from apps.core.models import Country, Region
from apps.stores.models import STORE_TYPE_TOKE, StoreLocation
from apps.stores.normalize import address_key, name_key, phone_key, slugify_name


class PlaceNotFound(Exception):
    """A country/state/area slug that names nothing. Views turn it into a 404."""


# ---------------------------------------------------------------------------
# querysets
# ---------------------------------------------------------------------------

def public_stores() -> QuerySet[StoreLocation]:
    """The rows a customer may see. The ONE definition of that, imported by every
    public code path — the alternative is four places that each remember two
    filters, and the day one of them forgets `archived_at` a deleted distributor
    is back on the website."""
    return StoreLocation.objects.filter(is_active=True, archived_at__isnull=True)


def _ordered(queryset: QuerySet[StoreLocation]) -> QuerySet[StoreLocation]:
    """Our own counters first, then alphabetical.

    Not `Meta.ordering`, because it is a presentation rule for the public list and
    the admin list wants plain alphabetical. Expressed as a CASE rather than by
    relying on "distributor" < "toke_store" alphabetically, which is true today and
    is not a property anybody should depend on.
    """
    return queryset.annotate(
        _type_rank=Case(
            When(store_type=STORE_TYPE_TOKE, then=Value(0)),
            default=Value(1),
            output_field=IntegerField(),
        )
    ).order_by("_type_rank", "name")


# ---------------------------------------------------------------------------
# the place cascade
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Place:
    """One option in one of the three dropdowns."""

    slug: str
    name: str
    store_count: int
    has_children: bool
    # Countries only; None for states and areas.
    code: str | None = None
    state_label: str | None = None
    area_label: str | None = None


def countries_with_stores() -> list[Place]:
    """Markets holding at least one visible store.

    `is_rest_of_world` is excluded: "ZZ / International" is a pricing bucket, not a
    place anybody can drive to, and offering it as a country to search would be a
    dropdown entry that can never be satisfied.
    """
    stores_here = public_stores().filter(country=OuterRef("pk"))
    areas_here = public_stores().filter(country=OuterRef("pk"), area_region__isnull=False)
    rows = (
        Country.objects.filter(is_rest_of_world=False)
        .annotate(has_stores=Exists(stores_here), has_areas=Exists(areas_here))
        .filter(has_stores=True)
        .order_by("-is_default", "name")
    )
    # One extra grouped query for the counts rather than an aggregate on the same
    # join as the two EXISTS subqueries — mixing them is how a count silently
    # becomes a row-multiplied lie.
    counts = _counts_by(public_stores(), "country_id")
    return [
        Place(
            slug=slugify_name(row.name),
            name=row.name,
            code=row.code,
            store_count=counts.get(row.code, 0),
            has_children=row.has_areas,
            state_label=row.state_label,
            area_label=row.area_label,
        )
        for row in rows
    ]


def states_with_stores(country: Country) -> list[Place]:
    stores_here = public_stores().filter(state_region=OuterRef("pk"))
    areas_here = public_stores().filter(state_region=OuterRef("pk"), area_region__isnull=False)
    rows = (
        Region.objects.filter(country_code=country.code, level="state")
        .annotate(has_stores=Exists(stores_here), has_areas=Exists(areas_here))
        .filter(has_stores=True)
        .order_by("name")
    )
    counts = _counts_by(public_stores().filter(country=country), "state_region_id")
    return [
        Place(
            slug=slugify_name(row.name),
            name=row.name,
            store_count=counts.get(row.id, 0),
            has_children=row.has_areas,
        )
        for row in rows
    ]


def areas_with_stores(state: Region) -> list[Place]:
    stores_here = public_stores().filter(area_region=OuterRef("pk"))
    rows = (
        Region.objects.filter(parent=state, level="area")
        .annotate(has_stores=Exists(stores_here))
        .filter(has_stores=True)
        .order_by("name")
    )
    counts = _counts_by(public_stores().filter(state_region=state), "area_region_id")
    return [
        Place(
            slug=slugify_name(row.name),
            name=row.name,
            store_count=counts.get(row.id, 0),
            has_children=False,
        )
        for row in rows
    ]


def _counts_by(queryset: QuerySet[StoreLocation], column: str) -> dict:
    """`{group value: number of stores}` in one grouped query."""
    from django.db.models import Count

    return {
        row[column]: row["n"]
        for row in queryset.values(column).annotate(n=Count("id"))
    }


# ---------------------------------------------------------------------------
# slug resolution
# ---------------------------------------------------------------------------

def resolve_country(slug: str) -> Country:
    """A country from either its slug ("nigeria") or its ISO code ("ng"/"NG").

    Both accepted because the storefront's own country cookie and the existing
    `/meta/` endpoints speak ISO codes, and refusing one of the two spellings
    would make every caller remember which. Matching is case-insensitive.
    """
    raw = (slug or "").strip()
    if not raw:
        raise PlaceNotFound("country")
    candidates = Country.objects.filter(is_rest_of_world=False)
    if len(raw) == 2:
        found = candidates.filter(code__iexact=raw).first()
        if found is not None:
            return found
    wanted = slugify_name(raw)
    for country in candidates:
        if slugify_name(country.name) == wanted:
            return country
    raise PlaceNotFound("country")


def resolve_region(slug: str, *, country: Country, parent: Region | None) -> Region:
    """A state (parent=None) or an area (parent=<state>) by slug.

    Resolved in PYTHON over the candidate rows rather than in SQL, because the
    slug is derived from `Region.name` and is not stored — there is no column to
    index. The candidate set is bounded and small by construction: 37 states for
    Nigeria, at most 57 LGAs inside one of them.

    ON COLLISION, the first alphabetically wins and that is deliberately arbitrary
    — `tests/test_slugs.py` asserts the seeded data has no collision in any scope,
    so reaching the tie-break means somebody added a region whose name slugifies
    onto an existing one, and the test says so before a customer does.

    RENAMES BREAK LINKS. A slug is derived, so renaming "Federal Capital Territory"
    to "FCT" 404s every shared /find-stores link naming it. That is the price of
    keeping database ids out of public URLs; the mitigation is that these names are
    seeded reference data that changes approximately never, and the failure is a
    polite "we could not find that place" rather than a broken page.
    """
    wanted = slugify_name(slug or "")
    if not wanted:
        raise PlaceNotFound("state" if parent is None else "area")
    if parent is None:
        candidates = Region.objects.filter(country_code=country.code, level="state")
    else:
        candidates = Region.objects.filter(parent=parent, level="area")
    for region in candidates.order_by("name"):
        if slugify_name(region.name) == wanted:
            return region
    raise PlaceNotFound("state" if parent is None else "area")


def stores_in(
    country: Country, state: Region | None = None, area: Region | None = None
) -> QuerySet[StoreLocation]:
    """The visible stores at the narrowest place given.

    A state-level query returns every store in the state INCLUDING those filed
    under one of its LGAs. The customer UI walks down to the LGA before it
    searches, so it normally passes one; the wider answer exists because a
    shared link can name a state whose LGA has since been archived, and "here is
    everything in Lagos" is a better answer than an empty page.
    """
    queryset = public_stores().filter(country=country)
    if state is not None:
        queryset = queryset.filter(state_region=state)
    if area is not None:
        queryset = queryset.filter(area_region=area)
    return _ordered(
        queryset.select_related("country", "state_region", "area_region")
    )


# ---------------------------------------------------------------------------
# links rendered for the customer
# ---------------------------------------------------------------------------

def maps_url(store: StoreLocation) -> str:
    """A "Get directions" target.

    Prefers the pin when there is one. Falls back to the composed address text,
    which is honest but imprecise — Nigerian street addresses geocode poorly, so
    the link lands the customer in the right neighbourhood rather than at the
    door. That is why `latitude`/`longitude` exist on the model even though
    nothing routes on them.
    """
    if store.latitude is not None and store.longitude is not None:
        query = f"{store.latitude},{store.longitude}"
    else:
        parts = [
            store.address,
            store.area_region.name if store.area_region_id else "",
            store.city_text,
            store.state_region.name if store.state_region_id else "",
            store.country.name if store.country_id else "",
        ]
        query = ", ".join(part for part in parts if part)
    return f"https://www.google.com/maps/search/?{urlencode({'api': '1', 'query': query})}"


def whatsapp_url(e164: str) -> str:
    """`https://wa.me/2348…` — wa.me wants digits with no plus and no punctuation."""
    digits = phone_key(e164)
    return f"https://wa.me/{quote(digits)}" if digits else ""


# ---------------------------------------------------------------------------
# duplicate detection
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DuplicateHint:
    kind: str          # "store" | "pickup_location"
    reason: str        # "name" | "address" | "phone"
    label: str         # what to show the operator
    detail: str
    id: int | None


# Enough digits to identify a subscriber without demanding the two callers agree
# about the country code. Nigerian mobile subscriber numbers are 10 digits after
# the "0"; nine is the shortest suffix that is still specific.
_PHONE_SUFFIX = 9


def possible_duplicates(
    *,
    country: Country,
    state: Region,
    area: Region | None,
    name: str,
    address: str,
    phones: list[str],
    exclude_pk: int | None = None,
) -> list[DuplicateHint]:
    """Rows that look like the shop being saved. A WARNING, never a refusal.

    The hard database constraint already refuses an exact re-entry (same name AND
    same address in the same place). Everything here is fuzzier than that and
    therefore cannot be a rule: two branches of one chain in one LGA share a name
    legitimately, a mall's counters share an address, and a distributor who also
    runs a salon shares a phone. So each hit is returned with the REASON it fired
    and the operator decides.

    `delivery.SenderLocation` is searched too. Those rows are the Toke counters
    parcels ship from, and the ones flagged `customer_pickup` are already offered
    to customers at checkout — filing one of them here again, unnoticed, is the
    single most likely way this directory starts disagreeing with checkout about
    where our own shops are.
    """
    from apps.delivery.models import SenderLocation

    wanted_name = name_key(name)
    wanted_address = address_key(address)
    suffixes = [
        digits[-_PHONE_SUFFIX:]
        for digits in (phone_key(p) for p in phones if p)
        if len(digits) >= _PHONE_SUFFIX
    ]

    # Scoped to the state, not the whole country: a shop with the same name in
    # another state is a branch, not a duplicate, and flagging it would train the
    # operator to click through the warning without reading it.
    scope = StoreLocation.objects.filter(country=country, state_region=state)
    if exclude_pk is not None:
        scope = scope.exclude(pk=exclude_pk)
    # Archived rows are included on purpose — "you archived this last month" is
    # exactly what somebody re-typing it needs to be told.
    #
    # A NAME match only counts inside the same LGA: "Beauty Hub" in Ikeja and
    # "Beauty Hub" in Alimosho are two shops of one chain, and flagging that pair
    # every time would train the operator to click through the warning unread. An
    # ADDRESS or PHONE match counts anywhere in the state, because neither is
    # place-dependent in the same way.
    name_q = Q(name_key=wanted_name)
    if area is not None:
        name_q &= Q(area_region=area)
    matches = name_q
    if wanted_address:
        matches |= Q(address_key=wanted_address)
    for suffix in suffixes:
        matches |= Q(phone__endswith=suffix) | Q(phone_alt__endswith=suffix)

    hints: list[DuplicateHint] = []
    for row in scope.filter(matches).select_related("area_region")[:10]:
        if row.name_key == wanted_name:
            reason = "name"
        elif row.address_key == wanted_address:
            reason = "address"
        else:
            reason = "phone"
        where = row.area_region.name if row.area_region_id else row.city_text
        hints.append(
            DuplicateHint(
                kind="store",
                reason=reason,
                label=row.name,
                detail=", ".join(part for part in [row.address, where] if part)
                + (" — archived" if row.is_archived else ""),
                id=row.pk,
            )
        )

    sender_matches = Q(pk__in=[])  # matches nothing until a real signal is added
    if address.strip():
        sender_matches |= Q(address__iexact=address.strip())
    for suffix in suffixes:
        sender_matches |= Q(phone__endswith=suffix)
    for row in SenderLocation.objects.filter(sender_matches)[:5]:
        hints.append(
            DuplicateHint(
                kind="pickup_location",
                reason="address" if address_key(row.address) == wanted_address else "phone",
                label=row.name,
                detail=(
                    "Already a Toke pickup location"
                    + (" offered to customers at checkout." if row.customer_pickup else ".")
                ),
                id=row.pk,
            )
        )
    return hints
