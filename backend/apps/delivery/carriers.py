"""Carrier decoration over the pure option matcher (Plan-32a slice 3).

`services.options_for_address` stays pure — no HTTP, its docstring is a
contract. This wrapper is what checkout calls instead: it passes manual options
through untouched and, for each `kind="carrier"` option, either fills a live
price or REMOVES the option. Removal is the failure mode by design: GIG being
down, an uncovered LGA, a missing centroid — none of them may block a checkout
that the flat-rate options can carry. The worst outcome of a carrier outage is
a customer paying the flat ₦3,500 instead of a live ₦2,900.

The customer-facing dict deliberately does NOT carry GIG's breakdown — it holds
our discount rank and cost structure, which is nobody's business at the cart.
The full payload sits in the quote cache under `carrier_quote_key`, where order
placement (slice 4) snapshots it.
"""
from __future__ import annotations

from decimal import Decimal

from apps.delivery.gig.centres import haversine_km
from apps.delivery.gig.quotes import (
    coverage_region,
    quote_centre_pickup,
    quote_home_delivery,
    receiver_point,
)
from apps.delivery.models import DeliveryOption, GigCentre
from apps.delivery.services import _total_weight_g, options_for_address


def nearest_centre(address):
    """The closest active centre to the address's pin (else LGA centroid), or None.
    Used to PRICE the pickup option in the list — the customer still chooses their
    actual centre in the picker (32b ruling 3), and placement re-quotes the chosen
    one server-side (slice 4)."""
    region = coverage_region(address, home_delivery=False)
    if region is None:
        return None
    lat, lng = receiver_point(address, region)
    best, best_km = None, None
    for centre in GigCentre.objects.filter(is_active=True).exclude(latitude=None).exclude(longitude=None):
        km = haversine_km(lat, lng, centre.latitude, centre.longitude)
        if best_km is None or km < best_km:
            best, best_km = centre, km
    return best


def priced_options_for_address(address, lines, subtotal: Decimal, country) -> list[dict]:
    """`options_for_address`, with carrier options live-priced or omitted."""
    options = options_for_address(address, lines, subtotal, country)
    if not any(o["kind"] == "carrier" for o in options):
        return options

    weight_g = _total_weight_g(lines)
    priced: list[dict] = []
    for option in options:
        if option["kind"] != "carrier":
            priced.append(option)
            continue
        if option["carrier_code"] != "gig":  # only GIG is wired up (DHL: Plan-32c)
            continue
        if option.get("carrier_service") == "pickup":
            centre = nearest_centre(address)
            quote = quote_centre_pickup(address, weight_g, declared_value=subtotal, centre=centre)
        else:
            quote = quote_home_delivery(address, weight_g, declared_value=subtotal)
        if quote is None:
            continue
        charged = quote.price
        # free_over applies to what the CUSTOMER pays, never to what GIG costs us —
        # the placement snapshot keeps both figures (spec ruling 2).
        row = DeliveryOption.objects.filter(pk=option["id"]).first()
        if row and row.free_over is not None and subtotal >= row.free_over:
            charged = Decimal("0.00")
        priced.append({
            **option,
            "price": str(charged),
            "carrier_quote_key": quote.cache_key,
        })
    return priced
