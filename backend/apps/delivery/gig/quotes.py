"""Checkout-time GIG quoting (Plan-32a slice 3).

The rules, all measured or ruled in the plan doc:

- A quote is attempted ONLY when the whole precondition chain holds: NG order,
  address resolves to an LGA region, an active `GigLga` with home delivery maps
  to it, and the region has a centroid. Anything short of that returns None and
  checkout simply doesn't offer GIG — the flat-rate options carry it.
- The HTTP budget is one attempt, 3 seconds, no retries. A checkout render must
  never hang on a carrier.
- Quotes are cached 6 hours per (LGA, ceil-kg) — measured: price ignores weight
  below 5 kg and coordinates resolve zone-granular, so this key over-segments if
  anything. The FULL quote payload is cached, not just the price: order
  placement (slice 4) re-reads it to snapshot the breakdown without a second
  HTTP call, which also guarantees the customer was charged exactly what the
  stored breakdown says.
- `GrandTotal` is authoritative — never recomputed from parts (it doesn't
  reconcile; measured twice, differently).
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from decimal import Decimal

from django.conf import settings
from django.core.cache import cache

from apps.delivery.gig import client

logger = logging.getLogger(__name__)

QUOTE_TIMEOUT_SECONDS = 3.0
QUOTE_CACHE_TTL = 6 * 60 * 60
TWO_DP = Decimal("0.01")


@dataclass(frozen=True)
class GigQuote:
    price: Decimal      # what the customer is charged (= GrandTotal, quantized)
    breakdown: dict     # GIG's full response payload, verbatim
    api_id: str
    cache_key: str


def _cache_key(region_id: int, weight_g: int) -> str:
    return f"gig:quote:v1:{region_id}:{max(1, math.ceil(weight_g / 1000))}"


def coverage_region(address):
    """The address's home-delivery-covered LGA region with a centroid, or None.

    Walks the address's regions (LGA first, then state — mirrors delivery
    matching's ancestor logic in spirit, but coverage is LGA-granular so only
    the area region can qualify)."""
    region = address.area_region
    if region is None or region.latitude is None or region.longitude is None:
        return None
    if not region.gig_lgas.filter(is_active=True, home_delivery=True).exists():
        return None
    return region


def quote_home_delivery(address, weight_g: int, declared_value: Decimal) -> GigQuote | None:
    """One cached-or-live quote, or None (meaning: don't offer GIG)."""
    region = coverage_region(address)
    if region is None:
        return None

    key = _cache_key(region.id, weight_g)
    cached = cache.get(key)
    if cached is not None:
        return GigQuote(
            price=Decimal(cached["price"]), breakdown=cached["breakdown"],
            api_id=cached["api_id"], cache_key=key,
        )

    body = {
        "SenderLocation": {
            "Latitude": settings.GIG_SENDER_LATITUDE,
            "Longitude": settings.GIG_SENDER_LONGITUDE,
        },
        "ReceiverLocation": {
            "Latitude": float(region.latitude),
            "Longitude": float(region.longitude),
        },
        "VehicleType": settings.GIG_VEHICLE_TYPE,
        "PickUpOptions": 0,  # home delivery; centre pickup is slice 32b
        "ShipmentItems": [{
            "ItemName": "Cosmetics order",
            "Quantity": 1,
            # GIG prices by vehicle + zone (weight measured irrelevant below 5 kg),
            # but send the true weight so heavier carts price honestly if that changes.
            "Weight": round(weight_g / 1000, 3) or 0.001,
            "ShipmentType": 1,  # Regular — the only value the live validator accepts
            "Value": float(declared_value),
            "IsVolumetric": False,
        }],
    }
    try:
        result = client.call(
            "POST", "/price/v3", body, timeout=QUOTE_TIMEOUT_SECONDS, retries=0
        )
    except client.GigError as exc:
        logger.warning("gig quote unavailable for region %s: %s", region.id, exc)
        return None

    payload = result.data.get("data", result.data) if isinstance(result.data, dict) else result.data
    if not isinstance(payload, dict) or "GrandTotal" not in payload:
        logger.warning("gig quote malformed for region %s (apiId=%s)", region.id, result.api_id)
        return None

    price = Decimal(str(payload["GrandTotal"])).quantize(TWO_DP)
    cache.set(key, {"price": str(price), "breakdown": payload, "api_id": result.api_id},
              QUOTE_CACHE_TTL)
    return GigQuote(price=price, breakdown=payload, api_id=result.api_id, cache_key=key)
