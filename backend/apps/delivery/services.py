"""Delivery-option matching + pricing. Pure domain: no HTTP, no Cart import — takes
an address, an iterable of (variant, qty) lines, and a subtotal. Reused by the cart
display and by checkout's server-side re-check (never trust the client's option list).
"""
from __future__ import annotations

from decimal import Decimal

from django.db.models import Q

from apps.delivery.models import DeliveryOption

TWO_DP = Decimal("0.01")


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
    """
    from apps.core.country_context import resolve_country

    resolved = resolve_country(address.country_code)
    if resolved is None:
        return []
    region_ids = _covered_region_ids(address)
    qs = (
        DeliveryOption.objects.filter(is_active=True)
        .filter(_coverage_q(resolved.code, region_ids))
        .prefetch_related("rates", "countries", "regions")
        .distinct()
        .order_by("sort", "name")
    )
    weight_g = _total_weight_g(lines)
    return [
        {
            "id": o.id,
            "name": o.name,
            "kind": o.kind,
            "currency": o.currency_id,
            "price": str(_price_for(o, weight_g, subtotal)),
            "min_days": o.min_days,
            "max_days": o.max_days,
        }
        for o in qs
    ]
