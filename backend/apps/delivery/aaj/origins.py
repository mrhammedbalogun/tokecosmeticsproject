"""Sender-origin selection for AAJ (Plan-43) — the GIG `origins.py` idea, re-cut for
a carrier that prices by STATE rather than by pin.

AAJ's price is (sender state, receiver state, weight). Two consequences:

1. The origin's STATE is load-bearing (measured: Abuja→Lagos ₦4,701 where
   Lagos→Lagos is ₦2,779). `SenderLocation.state` is free text and "display only"
   by its own docstring, and the seeded Ogudu row carries "". So the state is
   resolved in order of trust: `state_region` (an FK, set for pickup stores) →
   the free-text label when it names a real state → the parent state of the
   NEAREST LGA centroid to the row's pin (774 centroids; the pin is the one field
   every row must have). Nothing falls back to a constant: a row whose state
   cannot be resolved is SKIPPED, never priced as Lagos.
2. Selection prefers an origin IN the receiver's state (intra-state is the cheapest
   zone and the shortest ETA), then the nearest by haversine to the receiver's pin
   or LGA centroid, then the lowest pk. Deterministic, so a checkout re-render never
   flips origins (and cache keys) on a coin toss.

The chosen origin is SNAPSHOTTED onto `AajShipment.origin` at placement (through
the quote cache), so capture books from exactly what was priced even if the row is
edited or deactivated later. Zero usable rows = no AAJ option (there is no env-var
sender for AAJ; GIG's env fallback predates the sender table and AAJ never had one).
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass

from django.conf import settings

from apps.core.models import Region
from apps.delivery.aaj.states import canonical_state, state_code
from apps.delivery.gig.centres import haversine_km
from apps.delivery.models import SenderLocation

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Origin:
    id: int
    name: str
    phone: str
    address: str
    locality: str
    state_name: str   # our canonical state name ("Federal Capital Territory")
    state_code: str   # AAJ's code ("FCT")
    postal_code: str
    latitude: float
    longitude: float

    def as_snapshot(self) -> dict:
        return asdict(self)


def _state_from_pin(lat: float, lng: float) -> str | None:
    """The parent state of the nearest NG LGA centroid — an offline reverse geocode
    at LGA precision, which is far finer than the state boundary it has to find."""
    best, best_km = None, None
    rows = (
        Region.objects.filter(country_code="NG", level="area")
        .exclude(latitude=None).exclude(longitude=None)
        .select_related("parent")
        .only("latitude", "longitude", "parent__name")
    )
    for region in rows:
        km = haversine_km(lat, lng, region.latitude, region.longitude)
        if best_km is None or km < best_km:
            best, best_km = region, km
    return best.parent.name if best is not None and best.parent is not None else None


def resolve_state(row: SenderLocation) -> str | None:
    """Canonical state name for a sender row, or None when nothing trustworthy
    says where it is."""
    if row.state_region_id and row.state_region is not None:
        name = canonical_state(row.state_region.name)
        if name:
            return name
    name = canonical_state(row.state)
    if name:
        return name
    if row.latitude is not None and row.longitude is not None:
        return _state_from_pin(float(row.latitude), float(row.longitude))
    return None


def _row_origin(row: SenderLocation) -> Origin | None:
    state_name = resolve_state(row)
    code = state_code(state_name)
    if code is None:
        logger.warning("aaj origin %s (%s) skipped: state unresolvable", row.pk, row.name)
        return None
    return Origin(
        id=row.pk, name=row.name, phone=row.phone, address=row.address,
        locality=row.locality, state_name=state_name, state_code=code,
        postal_code=settings.AAJ_SENDER_POSTAL_CODE,
        latitude=float(row.latitude), longitude=float(row.longitude),
    )


def _receiver_point(address):
    lat, lng = getattr(address, "latitude", None), getattr(address, "longitude", None)
    if lat is not None and lng is not None:
        return float(lat), float(lng)
    area = getattr(address, "area_region", None)
    if area is not None and area.latitude is not None and area.longitude is not None:
        return float(area.latitude), float(area.longitude)
    return None


def usable_origins() -> list[Origin]:
    rows = SenderLocation.objects.filter(is_active=True).select_related("state_region").order_by("pk")
    return [o for o in (_row_origin(r) for r in rows) if o is not None]


def select_origin(address) -> Origin | None:
    """The origin this address is priced from (see module docstring), or None."""
    origins = usable_origins()
    if not origins:
        return None
    receiver_state = canonical_state(getattr(getattr(address, "state_region", None), "name", None))
    same_state = [o for o in origins if o.state_name == receiver_state]
    if same_state:
        return same_state[0]  # lowest pk: the list is pk-ordered
    point = _receiver_point(address)
    if point is None:
        return origins[0]
    best, best_km = None, None
    for origin in origins:
        km = haversine_km(point[0], point[1], origin.latitude, origin.longitude)
        if best_km is None or km < best_km:
            best, best_km = origin, km
    return best
