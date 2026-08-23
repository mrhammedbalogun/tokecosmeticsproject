"""Checkout-time AAJ quoting (Plan-43).

The rules, all measured on the sandbox 2026-08-23 (plan doc §2):

- A quote is attempted ONLY when: NG order, the address carries a `state_region`,
  and that state maps to an AAJ code in `states.py`. Nothing else gates it — AAJ
  serves all 37 states door-to-door, so unlike GIG there is no LGA sync, no
  centroid, no home-delivery flag. Anything short of the chain returns None and
  checkout simply doesn't offer AAJ.
- AAJ prices by (sender state, receiver state, ceil-kg weight). The city string,
  box dimensions and postal code do not move the price. The state CODE is what
  prices; an unknown code silently prices as Lagos — which is why `states.py`
  refuses to guess and this module omits the option on None.
- `POST /quote` prices WITHOUT creating a real booking (its `booking` id 404s on
  get-booking) and takes ~1.2–2.2 s. Budget: one attempt, 4 s, no retries.
- `total` is the price (it includes AAJ's 7.5% VAT) and is RETAIL. Our partner
  key books the same route ~14% cheaper (create-booking under the key prices at
  the account's rate), so the customer is never charged below cost; the margin
  is exactly `charged − cost` at reconciliation (capture.py records cost).
- Quotes are cached 6 h per (origin, receiver state, ceil-kg). The FULL payload
  is cached: placement re-reads it to snapshot the breakdown without a second
  HTTP call, so the customer is charged exactly what the stored breakdown says.
- The quote's `eta.numberOfDays` rides along: carriers.py shows it instead of the
  option row's static min/max days, because AAJ's own figure varies 2–8 days by
  state and the static pair cannot be honest for all of them.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from decimal import Decimal

from django.core.cache import cache

from apps.delivery.aaj import client
from apps.delivery.aaj.origins import select_origin
from apps.delivery.aaj.states import state_code

logger = logging.getLogger(__name__)

# Measured 1.2–2.2 s; a 3 s budget would drop the option intermittently and a
# customer who saw AAJ in the cart and not at checkout is a support ticket.
QUOTE_TIMEOUT_SECONDS = 4.0
QUOTE_CACHE_TTL = 6 * 60 * 60
TWO_DP = Decimal("0.01")
# A nominal carton: dimensions do not price (measured), but a packageDimension is
# REQUIRED per package and weight 0 leaves the actual weight as the chargeable one.
NOMINAL_BOX = {"length": 20, "width": 15, "height": 10, "weight": 0, "price": 0}


@dataclass(frozen=True)
class AajQuote:
    price: Decimal      # what the customer is charged (= total, quantized)
    breakdown: dict     # AAJ's quote object, verbatim
    eta_days: int | None
    cache_key: str


def _cache_key(origin_id: int, state_region_id: int, weight_g: int) -> str:
    return f"aaj:quote:v1:{origin_id}:{state_region_id}:{max(1, math.ceil(weight_g / 1000))}"


def weight_kg(weight_g: int) -> float:
    """Kilograms for AAJ's `actualWeight`, floored at 0.1 — create-booking refuses
    anything lighter (measured: "Actual weight must be at least 0.1"), and the
    ≤1 kg tier is one price, so the floor never moves a quote."""
    return max(round(weight_g / 1000, 3), 0.1)


def receiver_city(address) -> str:
    """AAJ requires a city of ≥2 characters and ignores it for pricing; it is
    printed on the label, so the LGA is the most useful truthful value."""
    area = getattr(address, "area_region", None)
    for candidate in (
        getattr(area, "name", None),
        getattr(address, "city_text", None),
        getattr(getattr(address, "state_region", None), "name", None),
    ):
        if candidate and len(candidate.strip()) >= 2:
            return candidate.strip()
    return "Unknown"


def coverage_state(address):
    """The address's state region when AAJ can price it, else None."""
    region = getattr(address, "state_region", None)
    if region is None or state_code(region.name) is None:
        return None
    return region


def address_details(*, line1: str, city: str, state_name: str, code: str, postal: str = "") -> dict:
    body = {
        "addressLine1": line1[:255] if line1 else city,
        "city": city,
        "state": state_name,
        "country": "Nigeria",
        "countryCode": "NG",
        "stateOrProvinceCode": code,
    }
    if postal:
        body["postalCode"] = postal
    return body


def quote_home_delivery(address, weight_g: int, declared_value: Decimal) -> AajQuote | None:
    """One cached-or-live quote, or None (meaning: don't offer AAJ)."""
    region = coverage_state(address)
    if region is None:
        return None
    code = state_code(region.name)

    origin = select_origin(address)
    if origin is None:
        return None  # no origin with a priceable state — logged inside select_origin
    key = _cache_key(origin.id, region.id, weight_g)
    cached = cache.get(key)
    if cached is not None:
        return AajQuote(
            price=Decimal(cached["price"]), breakdown=cached["breakdown"],
            eta_days=cached.get("eta_days"), cache_key=key,
        )

    body = {
        "sender": {"addressDetails": address_details(
            line1=origin.address, city=origin.locality or origin.state_name,
            state_name=origin.state_name, code=origin.state_code, postal=origin.postal_code,
        )},
        "receiver": {"addressDetails": address_details(
            line1="", city=receiver_city(address), state_name=region.name, code=code,
        )},
        "serviceType": "DOMESTIC",
        "carrier": "AAJ",
        "deliveryMode": "DOOR_STEP",
        "packages": {
            "itemsValue": float(declared_value),
            "packageType": "regular",
            "addOns": [],
            "packages": [{
                "unitMeasurement": "KGS",
                "actualWeight": weight_kg(weight_g),
                "packageDimension": NOMINAL_BOX,
            }],
        },
    }
    try:
        result = client.call("POST", "/quote", body, timeout=QUOTE_TIMEOUT_SECONDS, retries=0)
    except client.AajError as exc:
        logger.warning("aaj quote unavailable for state %s: %s", region.name, exc)
        return None

    quotes = result.data.get("quotes") if isinstance(result.data, dict) else None
    payload = next((q for q in (quotes or []) if isinstance(q, dict)), None)
    if payload is None or "total" not in payload:
        logger.warning("aaj quote malformed for state %s", region.name)
        return None
    try:
        price = Decimal(str(payload["total"])).quantize(TWO_DP)
    except Exception:  # pragma: no cover — a non-numeric total
        logger.warning("aaj quote total unparseable for state %s: %r", region.name, payload.get("total"))
        return None
    if price <= 0:
        logger.warning("aaj quote non-positive for state %s: %s", region.name, price)
        return None
    eta = payload.get("eta") or {}
    eta_days = eta.get("numberOfDays", eta.get("number_of_days"))
    eta_days = int(eta_days) if isinstance(eta_days, (int, float)) and eta_days > 0 else None
    # `origin` rides in the cached payload: placement lifts it onto
    # AajShipment.origin, so capture books from exactly what was priced.
    cache.set(key, {"price": str(price), "breakdown": payload, "eta_days": eta_days,
                    "origin": origin.as_snapshot()},
              QUOTE_CACHE_TTL)
    return AajQuote(price=price, breakdown=payload, eta_days=eta_days, cache_key=key)
