"""Checkout-time GIG quoting (Plan-32a slice 3).

The rules, all measured or ruled in the plan doc:

- A quote is attempted ONLY when the whole precondition chain holds: NG order,
  address resolves to an LGA region, an active `GigLga` with home delivery maps
  to it, and the region has a centroid. Anything short of that returns None and
  checkout simply doesn't offer GIG — the flat-rate options carry it.
- The HTTP budget is one attempt, 3 seconds, no retries. A checkout render must
  never hang on a carrier.
- Quotes are cached 6 hours per (origin, LGA, ceil-kg) — measured: price ignores weight
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
from apps.delivery.gig.origins import select_origin

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


def _cache_key(origin_id: int, region_id: int, weight_g: int) -> str:
    # v2 (Plan-34): the ORIGIN is in the key. Without it, two sender locations
    # would share cache entries and a customer could be charged one origin's
    # price while capture ships (and the wallet pays) from another.
    return f"gig:quote:v2:{origin_id}:{region_id}:{max(1, math.ceil(weight_g / 1000))}"


def _pickup_cache_key(origin_id: int, centre_id: int, weight_g: int) -> str:
    # Keyed on the CENTRE, not the LGA: the receiver is the centre's own location.
    return f"gig:quote:pickup:v2:{origin_id}:{centre_id}:{max(1, math.ceil(weight_g / 1000))}"


def receiver_point(address, region):
    """The customer's pin when they set one (Plan-32b: door coordinates for the
    rider), else the LGA centroid. Region is already validated to have one."""
    if getattr(address, "latitude", None) is not None and getattr(address, "longitude", None) is not None:
        return float(address.latitude), float(address.longitude)
    return float(region.latitude), float(region.longitude)


def coverage_region(address, *, home_delivery: bool = True):
    """The address's GIG-covered LGA region with a centroid, or None.

    `home_delivery=True` is the door-delivery precondition; `False` accepts any
    active LGA — centre pickup works wherever GIG operates at all (their dev,
    confirmed: non-home-delivery LGAs are pickup-only). Coverage is LGA-granular
    so only the area region can qualify."""
    region = address.area_region
    if region is None or region.latitude is None or region.longitude is None:
        return None
    lgas = region.gig_lgas.filter(is_active=True)
    if home_delivery:
        lgas = lgas.filter(home_delivery=True)
    if not lgas.exists():
        return None
    return region


def quote_home_delivery(address, weight_g: int, declared_value: Decimal) -> GigQuote | None:
    """One cached-or-live quote, or None (meaning: don't offer GIG)."""
    region = coverage_region(address)
    if region is None:
        return None

    # Origin follows the receiver (Plan-34 ruling 2): nearest active sender
    # location to the door pin (else centroid). Selected BEFORE the cache lookup
    # because the origin is part of the key.
    receiver_lat, receiver_lng = receiver_point(address, region)
    origin = select_origin(receiver_lat, receiver_lng)
    key = _cache_key(origin.id, region.id, weight_g)
    cached = cache.get(key)
    if cached is not None:
        return GigQuote(
            price=Decimal(cached["price"]), breakdown=cached["breakdown"],
            api_id=cached["api_id"], cache_key=key,
        )

    body = {
        "SenderLocation": {
            "Latitude": origin.latitude,
            "Longitude": origin.longitude,
        },
        "ReceiverLocation": {"Latitude": receiver_lat, "Longitude": receiver_lng},
        "VehicleType": settings.GIG_VEHICLE_TYPE,
        "PickUpOptions": 0,  # door delivery
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
    # `origin` rides in the cached payload (Plan-34 ruling 3): placement lifts it
    # onto GigShipment.origin, so capture ships from exactly what was priced.
    cache.set(key, {"price": str(price), "breakdown": payload, "api_id": result.api_id,
                    "origin": origin.as_snapshot()},
              QUOTE_CACHE_TTL)
    return GigQuote(price=price, breakdown=payload, api_id=result.api_id, cache_key=key)


def quote_centre_pickup(address, weight_g: int, declared_value: Decimal, centre) -> GigQuote | None:
    """One cached-or-live pickup quote to a specific GigCentre, or None.

    The centre's own coordinates are the receiver: the parcel travels to the
    centre, and the customer's pin plays no part in what GIG charges. Coverage
    precondition is only that the LGA is ACTIVE (pickup works wherever GIG
    operates), which the caller has already established via coverage_region(
    home_delivery=False)."""
    if centre is None or centre.latitude is None or centre.longitude is None:
        return None
    # The parcel travels origin→centre, so the origin follows the CENTRE's
    # coordinates — the customer's home plays no part in this leg (Plan-34
    # ruling 2).
    origin = select_origin(float(centre.latitude), float(centre.longitude))
    key = _pickup_cache_key(origin.id, centre.gig_centre_id, weight_g)
    cached = cache.get(key)
    if cached is not None:
        return GigQuote(price=Decimal(cached["price"]), breakdown=cached["breakdown"],
                        api_id=cached["api_id"], cache_key=key)
    body = {
        "SenderLocation": {"Latitude": origin.latitude,
                           "Longitude": origin.longitude},
        "ReceiverLocation": {"Latitude": float(centre.latitude), "Longitude": float(centre.longitude)},
        "VehicleType": settings.GIG_VEHICLE_TYPE,
        "PickUpOptions": 1,  # customer collects from the centre
        "ShipmentItems": [{"ItemName": "Cosmetics order", "Quantity": 1,
                           "Weight": round(weight_g / 1000, 3) or 0.001,
                           "ShipmentType": 1, "Value": float(declared_value),
                           "IsVolumetric": False}],
    }
    try:
        result = client.call("POST", "/price/v3", body, timeout=QUOTE_TIMEOUT_SECONDS, retries=0)
    except client.GigError as exc:
        logger.warning("gig pickup quote unavailable for centre %s: %s", centre.gig_centre_id, exc)
        return None
    payload = result.data.get("data", result.data) if isinstance(result.data, dict) else result.data
    if not isinstance(payload, dict) or "GrandTotal" not in payload:
        logger.warning("gig pickup quote malformed (apiId=%s)", result.api_id)
        return None
    price = Decimal(str(payload["GrandTotal"])).quantize(TWO_DP)
    cache.set(key, {"price": str(price), "breakdown": payload, "api_id": result.api_id,
                    "origin": origin.as_snapshot()},
              QUOTE_CACHE_TTL)
    return GigQuote(price=price, breakdown=payload, api_id=result.api_id, cache_key=key)
