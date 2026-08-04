"""GIG service-centre sync and the nearest-centres helper (Plan-32b slice 1).

The sweep walks `localstations/get` then `serviceCentresByStation?StationId=` per
station — the same only-filter-they-allow pattern as the LGA sync. Coordinates
arrive as strings or numbers depending on the row (measured); both are taken.
Distance is plain haversine over data we already hold — no third-party call ever
sits between a shopper and the centre list.
"""
from __future__ import annotations

import logging
import math
from decimal import Decimal, InvalidOperation

from django.utils import timezone

from apps.delivery.gig import client
from apps.delivery.models import GigCentre

logger = logging.getLogger(__name__)


def _dec(value):
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value)).quantize(Decimal("0.000001"))
    except (InvalidOperation, ValueError):
        return None


def _rows(result):
    data = result.data if isinstance(result.data, list) else (result.data or {}).get("data", [])
    return data or []


def sync_gig_centres() -> dict:
    stations = _rows(client.call("GET", "/localstations/get"))
    now = timezone.now()
    existing = {c.gig_centre_id: c for c in GigCentre.objects.all()}
    created = updated = 0
    for station in stations:
        station_id = station.get("StationId")
        if station_id is None:
            continue
        centres = _rows(client.call("GET", f"/serviceCentresByStation?StationId={station_id}"))
        for row in centres:
            centre_id = row.get("ServiceCentreId") or row.get("ServiceCenterId")
            if centre_id is None:
                continue
            fields = {
                "gig_station_id": station_id,
                "name": str(row.get("ServiceCentreName") or row.get("Name") or "")[:200],
                "address": str(row.get("Address", "") or "")[:500],
                "latitude": _dec(row.get("Latitude")),
                "longitude": _dec(row.get("Longitude")),
                "is_active": True,
                "synced_at": now,
            }
            obj = existing.get(centre_id)
            if obj is None:
                existing[centre_id] = GigCentre.objects.create(gig_centre_id=centre_id, **fields)
                created += 1
            else:
                changed = [k for k, v in fields.items() if getattr(obj, k) != v]
                if changed:
                    for k in changed:
                        setattr(obj, k, fields[k])
                    obj.save(update_fields=changed)
                    if changed != ["synced_at"]:
                        updated += 1
    deactivated = (
        GigCentre.objects.filter(is_active=True).exclude(synced_at=now).update(is_active=False)
    )
    counts = {"stations": len(stations), "centres": len(existing),
              "created": created, "updated": updated, "deactivated": deactivated}
    logger.info("gig centre sync: %s", counts)
    return counts


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    rlat1, rlon1, rlat2, rlon2 = map(math.radians, (float(lat1), float(lon1), float(lat2), float(lon2)))
    a = (math.sin((rlat2 - rlat1) / 2) ** 2
         + math.cos(rlat1) * math.cos(rlat2) * math.sin((rlon2 - rlon1) / 2) ** 2)
    return 2 * 6371.0 * math.asin(math.sqrt(a))


def nearest_centres(latitude, longitude, *, limit: int = 5) -> list[dict]:
    """Active centres with coordinates, sorted by distance from the given point.
    Sorted, not chosen: the customer picks (plan ruling 3)."""
    out = []
    for centre in GigCentre.objects.filter(is_active=True).exclude(latitude=None).exclude(longitude=None):
        out.append({
            "id": centre.gig_centre_id,
            "name": centre.name,
            "address": centre.address,
            "distance_km": round(haversine_km(latitude, longitude, centre.latitude, centre.longitude), 1),
        })
    out.sort(key=lambda c: c["distance_km"])
    return out[:limit]
