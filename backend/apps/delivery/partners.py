"""PartnerShipment lifecycle hooks that other apps call — the partner analogue of
`gig/shipments.py`, one step simpler because there is nothing to quote, capture or
track. Checkout calls `create_partner_shipment` inside the placement transaction;
the order state machine's deferred-effects lane calls `mark_delivered` when an
order reaches `delivered`.
"""
from __future__ import annotations

import logging

from django.utils import timezone

from apps.delivery.models import DeliveryPartner, PartnerShipment, PartnerZone

logger = logging.getLogger(__name__)


def _zone_pk(option_id) -> int | None:
    """The PartnerZone pk inside a "pz:{pk}" option id, or None."""
    raw = str(option_id or "")
    if not raw.startswith("pz:"):
        return None
    try:
        return int(raw[3:])
    except ValueError:
        return None


def create_partner_shipment(order, chosen: dict, charged) -> PartnerShipment | None:
    """Snapshot the chosen partner zone onto the order, same transaction as placement.

    `chosen` is the option dict services.py built ("pz:{pk}" id, the partner's slug
    in carrier_code). The zone row is RE-READ here rather than trusted from the
    dict for two reasons: the snapshot wants `dispatch_zone` (never in the dict)
    and `cost` must be the RAW zone price — `chosen["price"]` is post-fee-mask,
    which is `charged`'s number, not the partner's.

    If the zone vanished in the microseconds since options were priced, the
    shipment is still created from the option dict (the order IS going out via the
    partner; that fact must not depend on a rate-card row) with cost=None and no
    dispatch_zone. Only when even the partner cannot be named is nothing recorded
    — a guessed FK would be worse than an honest absence.
    """
    pk = _zone_pk(chosen.get("id"))
    zone = (
        PartnerZone.objects.select_related("partner").filter(pk=pk).first()
        if pk is not None
        else None
    )
    if zone is not None:
        return PartnerShipment.objects.create(
            order=order,
            partner=zone.partner,
            zone={
                "id": zone.pk,
                "lcda": zone.lcda_name,
                "areas": zone.areas_covered,
                "dispatch_zone": zone.dispatch_zone,
                "min_days": zone.min_days,
                "max_days": zone.max_days,
            },
            cost=zone.price,
            charged=charged,
        )

    partner = DeliveryPartner.objects.filter(code=chosen.get("carrier_code", "")).first()
    if partner is None:
        logger.warning(
            "partner shipment not recorded for order %s: option %r names no partner",
            order.number, chosen.get("id"),
        )
        return None
    logger.warning(
        "partner zone %r missing at placement for order %s; snapshotting the option dict",
        chosen.get("id"), order.number,
    )
    # "Door Delivery - {lcda} ({partner.name})" — services.py composed it, so it can
    # be decomposed; anything unexpected keeps the whole name as the lcda label.
    name = chosen.get("name", "")
    lcda = name.removeprefix("Door Delivery - ").removesuffix(f" ({partner.name})")
    return PartnerShipment.objects.create(
        order=order,
        partner=partner,
        zone={
            "id": pk,
            "lcda": lcda,
            "areas": chosen.get("areas_covered", ""),
            "min_days": chosen.get("min_days"),
            "max_days": chosen.get("max_days"),
        },
        cost=None,
        charged=charged,
    )


def mark_delivered(order_pk: int) -> None:
    """Deferred effect for orders reaching `delivered`: stamp the moment on the
    shipment, once. Filtered on isnull so a legal second pass through `delivered`
    (on_hold triage) keeps the FIRST timestamp — the delivery happened when it
    happened. A no-op for the vast majority of orders, which have no partner row."""
    updated = PartnerShipment.objects.filter(
        order_id=order_pk, delivered_at__isnull=True
    ).update(delivered_at=timezone.now())
    if updated:
        logger.info("partner shipment marked delivered for order pk %s", order_pk)
