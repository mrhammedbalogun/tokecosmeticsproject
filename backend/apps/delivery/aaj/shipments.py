"""AajShipment lifecycle hooks that other apps call (Plan-43).

Checkout calls `create_quoted_shipment` inside the placement transaction; the
order state machine's deferred-effects lane calls `abandon_quoted_shipment` when
an order reaches a dead status. Capture lives in capture.py — this module is only
what placement and death need, so checkout's import stays thin.
"""
from __future__ import annotations

import logging
from decimal import Decimal

from django.core.cache import cache

from apps.delivery.models import AajShipment

logger = logging.getLogger(__name__)


def create_quoted_shipment(order, chosen: dict, charged) -> AajShipment:
    """Snapshot the checkout quote onto the order, same transaction as placement.

    The quote payload comes from the cache under the option's `carrier_quote_key`
    — warm by construction, because place_order itself just priced this option.
    If it expired in the microseconds since, the shipment is still created (the
    order IS going out via AAJ; that fact must not depend on a cache) with an
    empty quote and a log line; capture then re-quotes nothing — create-booking
    prices the real cost itself.
    """
    quote = cache.get(chosen.get("carrier_quote_key", "")) or {}
    if not quote:
        logger.warning("aaj quote cache miss at placement for order %s", order.number)
    quote_total = None
    if quote.get("price") is not None:
        try:
            quote_total = Decimal(str(quote["price"]))
        except Exception:  # pragma: no cover — cache holds what we wrote
            quote_total = None
    return AajShipment.objects.create(
        order=order, status="quoted", quote=quote, quote_total=quote_total,
        charged=charged, origin=quote.get("origin") or {},
    )


def abandon_quoted_shipment(order_pk: int) -> None:
    """Deferred effect for cancelled/expired/refunded orders.

    `quoted` → `abandoned` outright. `booked` → `abandoned` too, AND the unpaid
    booking at AAJ is deleted best-effort through a Celery task — it holds the
    customer's name, phone and email as a DUE record under a customBookingId AAJ
    cannot search, so left alone it would sit there forever. The HTTP stays out of
    this on_commit lane on purpose (the lane is DB-only; a carrier outage must
    not break an order transition).

    A shipment that reached process-booking keeps its state: a refunded shipped
    order still has a real tracking id and a real charge, and erasing that would
    falsify the reconciliation trail. Staff are told instead (tasks.py)."""
    booked = list(
        AajShipment.objects.filter(order_id=order_pk, status="booked")
        .exclude(booking_id="").values_list("pk", "booking_id")
    )
    updated = AajShipment.objects.filter(
        order_id=order_pk, status__in=("quoted", "booked")
    ).update(status="abandoned")
    if updated:
        logger.info("aaj shipment abandoned for order pk %s", order_pk)
    for shipment_pk, booking_id in booked:
        from apps.delivery.tasks import delete_aaj_booking

        try:
            delete_aaj_booking.delay(shipment_pk, booking_id)
        except Exception as exc:  # broker down: the booking lingers, the order still dies
            logger.warning("aaj delete-booking enqueue failed for %s: %s", booking_id, exc)
