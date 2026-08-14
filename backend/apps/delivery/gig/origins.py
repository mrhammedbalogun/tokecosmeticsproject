"""Sender-origin selection (Plan-34).

One selection per quote: the nearest active `SenderLocation` to the RECEIVER
point — the door pin (else LGA centroid) for home delivery, the centre's own
coordinates for pickup, because the parcel travels origin→centre and the
customer's home plays no part in that leg. Haversine over rows we hold; no HTTP.
Deliberately NOT cheapest-of-N (plan ruling 2): that doubles GIG calls per
render, and GIG's zone pricing makes nearest ≈ cheapest.

Zero active rows returns the `GIG_SENDER_*` settings as a pseudo-origin with
id 0 — byte-for-byte the pre-Plan-34 behaviour, so an empty or fully
deactivated table degrades to "everything ships from the env origin", never to
a quote-less checkout.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from django.conf import settings

from apps.delivery.gig.centres import haversine_km
from apps.delivery.models import SenderLocation

SETTINGS_ORIGIN_ID = 0  # snapshot marker: "the env vars as they stood"


@dataclass(frozen=True)
class Origin:
    id: int
    name: str
    phone: str
    address: str
    locality: str
    latitude: float
    longitude: float

    def as_snapshot(self) -> dict:
        return asdict(self)


def settings_origin() -> Origin:
    return Origin(
        id=SETTINGS_ORIGIN_ID,
        name=settings.GIG_SENDER_NAME,
        phone=settings.GIG_SENDER_PHONE,
        address=settings.GIG_SENDER_ADDRESS,
        locality=settings.GIG_SENDER_LOCALITY,
        latitude=settings.GIG_SENDER_LATITUDE,
        longitude=settings.GIG_SENDER_LONGITUDE,
    )


def _row_origin(row: SenderLocation) -> Origin:
    return Origin(
        id=row.pk, name=row.name, phone=row.phone, address=row.address,
        locality=row.locality, latitude=float(row.latitude), longitude=float(row.longitude),
    )


def select_origin(receiver_lat, receiver_lng) -> Origin:
    """The nearest active sender location to the receiver point, else the
    settings fallback. Ties break to the lowest pk — deterministic, so the same
    checkout re-render never flips origins (and cache keys) on a coin toss."""
    best, best_km = None, None
    for row in SenderLocation.objects.filter(is_active=True).order_by("pk"):
        km = haversine_km(receiver_lat, receiver_lng, row.latitude, row.longitude)
        if best_km is None or km < best_km:
            best, best_km = row, km
    if best is None:
        return settings_origin()
    return _row_origin(best)
