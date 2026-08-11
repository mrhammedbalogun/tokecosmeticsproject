"""GigShipment lifecycle hooks that other apps call (Plan-32a slice 4).

Checkout calls `create_quoted_shipment` inside the placement transaction; the
order state machine's deferred-effects lane calls `abandon_quoted_shipment`
when an order reaches a dead status. Capture (slice 5) lives elsewhere — this
module is only what placement and death need, so checkout's import stays thin.
"""
from __future__ import annotations

import logging

from django.core.cache import cache

from apps.delivery.models import GigShipment

logger = logging.getLogger(__name__)


def create_quoted_shipment(order, chosen: dict, charged, *, centre=None) -> GigShipment:
    """Snapshot the checkout quote onto the order, same transaction as placement.

    The quote payload comes from the cache under the option's `carrier_quote_key`
    — warm by construction, because place_order itself just priced this option.
    If it expired in the microseconds since, the shipment is still created (the
    order IS going out via GIG; that fact must not depend on a cache) with an
    empty quote and a log line, and capture re-quotes before debiting.

    `centre` is the customer's chosen GigCentre for pickup orders (32b ruling 4):
    name, address and GIG ids are snapshotted, not FK'd — the row must answer
    "where do I collect" even after the centre vanishes from a nightly sync.
    """
    quote = cache.get(chosen.get("carrier_quote_key", "")) or {}
    if not quote:
        logger.warning("gig quote cache miss at placement for order %s", order.number)
    snapshot = (
        {"id": centre.gig_centre_id, "station_id": centre.gig_station_id,
         "name": centre.name, "address": centre.address,
         # Capture ships these as ReceiverLocation (slice 5) — snapshotted so the
         # waybill goes where the customer CHOSE even if the centre row moves.
         "latitude": float(centre.latitude) if centre.latitude is not None else None,
         "longitude": float(centre.longitude) if centre.longitude is not None else None}
        if centre is not None
        else {}
    )
    return GigShipment.objects.create(
        order=order, status="quoted", quote=quote, charged=charged, centre=snapshot
    )


def abandon_quoted_shipment(order_pk: int) -> None:
    """Deferred effect for cancelled/expired/refunded orders: a shipment that was
    only ever QUOTED becomes abandoned. One that reached capture keeps its state —
    a refunded shipped order still has a real waybill and a real wallet debit,
    and erasing that would falsify the reconciliation trail."""
    updated = GigShipment.objects.filter(order_id=order_pk, status="quoted").update(
        status="abandoned"
    )
    if updated:
        logger.info("gig shipment abandoned for order pk %s", order_pk)
