"""Delivery-option matching + pricing. Pure domain: no HTTP, no Cart import — takes
an address, an iterable of (variant, qty) lines, and a subtotal. Reused by the cart
display and by checkout's server-side re-check (never trust the client's option list).
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Q

from apps.core.country_context import resolve_country
from apps.delivery.models import (
    DeliveryBlock,
    DeliveryFeeMask,
    DeliveryOption,
    DeliveryPartner,
    PartnerZone,
    SenderLocation,
)

TWO_DP = Decimal("0.01")

# The store-pickup option's id in the mixed id space (int pks / "pz:{pk}" / this).
# ONE option however many stores serve the state — the customer picks the store in
# the checkout picker, exactly as GIG pickup picks a centre, and placement receives
# the store as `pickup_store_id` beside this option id.
STORE_PICKUP_OPTION_ID = "store_pickup"


def option_id_matches(option_id, raw) -> bool:
    """True when a client-submitted delivery_option_id names this option. Compared as
    STRINGS because the id space is mixed since Plan-39: DeliveryOption rows keep
    their integer pks, partner zones ride as "pz:{pk}" — and the id arrives as an int
    from older clients, a string from newer ones, or None. str() folds all of that
    into one comparison; None becomes "None", which no id ever equals."""
    return raw is not None and str(option_id) == str(raw)


def _partner_options(resolved_code: str, country, region_ids: set[int]) -> list[dict]:
    """Delivery-partner rate-card rows serving this address (Plan-39), as option
    dicts. Appended AFTER the DeliveryOption list — 'extra option, customer picks'
    was the ruling, so partner rows never displace or reorder the standing options.

    Gated to NGN orders in Nigeria: PartnerZone prices are implicitly NGN (the model
    docstring), and this is the same never-mix-currencies discipline
    options_for_address applies to DeliveryOption rows. A null price or an inactive
    row/partner never surfaces — null means "the partner has not priced this zone",
    which must not be renderable as free.
    """
    if resolved_code != "NG" or country.currency_id != "NGN" or not region_ids:
        return []
    zones = (
        PartnerZone.objects.filter(
            is_active=True, partner__is_active=True, price__isnull=False,
            lga_region_id__in=region_ids,
        )
        .select_related("partner")
        .order_by("lcda_name", "id")
    )
    return [
        {
            "id": f"pz:{z.id}",
            "name": f"Door Delivery - {z.lcda_name} ({z.partner.name})",
            "kind": "partner",
            "carrier_code": z.partner.code,
            "carrier_service": "home",
            "currency": "NGN",
            "price": str(Decimal(z.price).quantize(TWO_DP)),
            "quote_required": False,
            "disclaimer": "",
            "min_days": z.min_days,
            "max_days": z.max_days,
            # The doc's "Major Locations & Landmarks", rendered by the storefront as
            # "Areas covered: …" — the customer's cue for whether this LCDA is theirs.
            "areas_covered": z.areas_covered,
        }
        for z in zones
    ]


def pickup_stores_for_address(address) -> list[SenderLocation]:
    """The active customer-pickup stores in the address's STATE (Plan-40), nearest
    first when the address carries a pin (else the admin's alphabetical order).

    By state and deliberately not by LGA — the ruling is that every opted-in Lagos
    store shows to every Lagos customer. The match is FK-to-FK on `state_region`
    (the address serializer already resolves states to core.Region rows), so the
    free-text `SenderLocation.state` label can never hide a store from its state.
    """
    state_id = getattr(address, "state_region_id", None)
    if not state_id:
        return []
    stores = list(
        SenderLocation.objects.filter(
            is_active=True, customer_pickup=True, state_region_id=state_id
        ).order_by("name")
    )
    if stores and address.latitude is not None and address.longitude is not None:
        # Lazy import: haversine lives beside the GIG sync client, and this module's
        # contract is no-HTTP purity — pulling that module in at import time would
        # couple every options read to it for one math function.
        from apps.delivery.gig.centres import haversine_km

        stores.sort(key=lambda s: haversine_km(
            address.latitude, address.longitude, s.latitude, s.longitude
        ))
    return stores


def _store_pickup_option(resolved_code: str, country, address) -> list[dict]:
    """The zero-fee "Pickup at Toke Cosmetics Store" option (Plan-40), or [].

    Same NG + NGN gate as `_partner_options` — the fee is ₦0 whatever the browsing
    currency, but keeping one gate for every synthesised NG option means one rule to
    reason about. The serving stores ride INSIDE the option dict (`stores`): the list
    is a function of the address's state, computed exactly where the state match
    already happened, so the storefront picker needs no second endpoint and can never
    show a store the option itself would refuse.
    """
    if resolved_code != "NG" or country.currency_id != "NGN":
        return []
    stores = pickup_stores_for_address(address)
    if not stores:
        return []
    lat = address.latitude
    lng = address.longitude
    rows = []
    for s in stores:
        row = {"id": s.id, "name": s.name, "address": s.address, "phone": s.phone}
        if lat is not None and lng is not None:
            from apps.delivery.gig.centres import haversine_km

            row["distance_km"] = round(haversine_km(lat, lng, s.latitude, s.longitude), 1)
        rows.append(row)
    return [{
        "id": STORE_PICKUP_OPTION_ID,
        "name": "Pickup at Toke Cosmetics Store",
        "kind": "store",
        "carrier_code": "toke",
        "carrier_service": "pickup",
        "currency": "NGN",
        # A REAL zero, not None: the customer collects, so there is genuinely
        # nothing to pay — unlike quote_required's "unknown, never render as Free".
        "price": "0.00",
        "quote_required": False,
        "disclaimer": "",
        "min_days": 0,
        "max_days": 1,
        "stores": rows,
    }]


def service_code_for(option: dict) -> str:
    """The stable code Plan-41 block/mask rules are keyed on. GIG's two rows (door +
    centre pickup) share "gig" on purpose — the operator's mental model is the
    courier, not the row — and each manual option is its own service ("option:{pk}")
    because each one is its own courier arrangement."""
    kind = option.get("kind", "manual")
    if kind in ("carrier", "partner"):
        return option.get("carrier_code") or f"option:{option['id']}"
    if kind == "store":
        return STORE_PICKUP_OPTION_ID
    return f"option:{option['id']}"


def known_delivery_services() -> list[dict]:
    """Every service a block/mask rule can name — the admin picker's data and the
    write-side validation set. Inactive partners and options are listed deliberately:
    a rule outlives a kill-switch flip, and hiding the code would strand existing
    rules unlabelled in the admin."""
    services = [{"code": "gig", "name": "GIG Logistics", "kind": "carrier"}]
    services += [
        {"code": p.code, "name": p.name, "kind": "partner"}
        for p in DeliveryPartner.objects.order_by("name")
    ]
    services.append({
        "code": STORE_PICKUP_OPTION_ID,
        "name": "Pickup at Toke Cosmetics Store",
        "kind": "store",
    })
    services += [
        {"code": f"option:{o.pk}", "name": o.name, "kind": "manual"}
        for o in DeliveryOption.objects.filter(kind="manual").order_by("sort", "name")
    ]
    return services


def blocked_service_codes(country_code: str, region_ids: set[int]) -> set[str]:
    """The service codes DeliveryBlock rules remove at this address (Plan-41). A
    rule's narrowest set level decides: area beats state beats whole-country.
    Matching runs against the same ancestor-closure set the coverage matcher uses,
    so "block Lagos" catches every Lagos LGA exactly as "cover Lagos" offers to
    them — including an address that names the state but no LGA."""
    codes: set[str] = set()
    for rule in DeliveryBlock.objects.filter(is_active=True, country_code=country_code):
        if rule.area_region_id is not None:
            hit = rule.area_region_id in region_ids
        elif rule.state_region_id is not None:
            hit = rule.state_region_id in region_ids
        else:
            hit = True  # whole-country rule
        if hit:
            codes.add(rule.service_code)
    return codes


def fee_mask_percents() -> dict[str, Decimal]:
    """service_code → active markup percent (Plan-41). Zero-percent rows are dropped
    here so every caller can treat "no row" and "+0%" identically."""
    return {
        m.service_code: m.percent
        for m in DeliveryFeeMask.objects.filter(is_active=True)
        if m.percent
    }


def apply_fee_mask(price: Decimal, percent) -> Decimal:
    """price plus percent% of price, kobo-exact (half-kobo rounds up). ₦0 stays ₦0 —
    a free option masks to free, so free_over and store pickup are never disturbed."""
    if not percent:
        return price
    factor = Decimal("1") + Decimal(percent) / Decimal("100")
    return (price * factor).quantize(TWO_DP, rounding=ROUND_HALF_UP)


def _coverage_q(country_code: str, region_ids: set[int]):
    """An option matches when it covers the address's resolved country OR any covered
    region (the address's own region or any ancestor). The region leg is constrained to
    the same country: a Region carries its own country_code, and without this an option
    attached only to a Lagos region could be reached by a non-NG address that somehow
    carried an NG region FK."""
    q = Q(countries__code=country_code)
    if region_ids:
        q |= Q(regions__id__in=region_ids, regions__country_code=country_code)
    return q


def _covered_region_ids(address) -> set[int]:
    """The address's region and every ancestor — an option covering any of these
    matches. Walks parent links (tree depth ≤ 3, so ≤ a few queries)."""
    ids: set[int] = set()
    for region in (address.area_region, address.state_region):
        node = region
        while node is not None:
            ids.add(node.id)
            node = node.parent
    return ids


def _total_weight_g(lines) -> int:
    return sum((v.weight_grams or 0) * qty for v, qty in lines)


def _price_for(option, weight_g: int, subtotal: Decimal) -> Decimal:
    rates = list(option.rates.all())
    if rates:
        price = None
        for r in rates:
            if weight_g >= r.min_weight_g and (r.max_weight_g is None or weight_g <= r.max_weight_g):
                price = r.price
                break
        if price is None:  # over the top tier → use the highest tier's price
            price = rates[-1].price
    else:
        price = option.price
    if option.free_over is not None and subtotal >= option.free_over:
        return Decimal("0.00")
    return Decimal(price).quantize(TWO_DP)


def options_for_address(address, lines, subtotal: Decimal, country) -> list[dict]:
    """Return the active delivery options serving this address, each with a computed
    price and ETA. `lines` = iterable of (ProductVariant, qty); `subtotal` in the
    order currency (for free_over); `country` is the ORDER's country (browsing
    context), which is not necessarily the address's.

    The address's country is resolved through the same resolve_country() used for
    pricing context, so delivery and currency can never disagree about what country
    an address is in. An unknown/inactive ISO code (a real "DE") resolves to the
    Rest-of-World row; a KNOWN country with no options configured returns [] and the
    caller raises delivery_option_invalid. The trigger is an unknown code, never an
    empty result — "no options found => use ZZ" would silently serve international
    pricing to GB customers the day someone deactivates the last GB option.

    Options are filtered to the ORDER's currency. compute_totals takes a bare
    delivery amount and knows nothing about the option's currency, so an option in
    another currency would have its number added to the order as if it were the
    order's currency. Blocking is deliberate (see the spec): converting via an FX
    rate would put FX into the totals maths for a rare case.
    """
    resolved = resolve_country(address.country_code)
    if resolved is None:
        return []
    region_ids = _covered_region_ids(address)
    qs = (
        DeliveryOption.objects.filter(is_active=True)
        .filter(currency_id=country.currency_id)
        .filter(_coverage_q(resolved.code, region_ids))
        .prefetch_related("rates", "countries", "regions")
        .distinct()
        .order_by("sort", "name")
    )
    weight_g = _total_weight_g(lines)
    rows = [
        {
            "id": o.id,
            "name": o.name,
            "kind": o.kind,
            "carrier_code": o.carrier_code,
            "carrier_service": o.carrier_service,
            "currency": o.currency_id,
            # None, never "0.00": an unknown cost must not be renderable as "Free".
            "price": None if o.quote_required else str(_price_for(o, weight_g, subtotal)),
            "quote_required": o.quote_required,
            "disclaimer": o.disclaimer,
            "min_days": o.min_days,
            "max_days": o.max_days,
        }
        for o in qs
    ]
    options = (
        rows
        + _partner_options(resolved.code, country, region_ids)
        + _store_pickup_option(resolved.code, country, address)
    )

    # Plan-41 blocks: subtractive, after every source has contributed, so one rule
    # reaches manual, carrier, partner and store options alike.
    blocked = blocked_service_codes(resolved.code, region_ids)
    if blocked:
        options = [o for o in options if service_code_for(o) not in blocked]

    # Plan-41 fee masks. Carrier rows are skipped: their price here is a placeholder
    # that carriers.py replaces with the live quote — the mask is applied there, once,
    # to the real number. quote_required rows carry no price to mask.
    masks = fee_mask_percents()
    if masks:
        for o in options:
            if o["kind"] == "carrier" or o["price"] is None:
                continue
            percent = masks.get(service_code_for(o))
            if percent:
                o["price"] = str(apply_fee_mask(Decimal(o["price"]), percent))
    return options
