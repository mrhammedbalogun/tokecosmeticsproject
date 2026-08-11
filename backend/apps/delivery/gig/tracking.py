"""The tracking poll (Plan-32a slice 6) — pull now, webhook at go-live.

GIG's status vocabulary is UNPUBLISHED. We have observed `MCRT` (created), the
docs name `MAHD`/`DLP`/`CRT` without definitions, and their developer described
an "Assigned" stage. So the map below is openly incomplete and the rules are
built for that:

- `DLP` is delivery (the only code the docs' own example ties to a delivered
  parcel). It moves the shipment to `delivered` and attempts the order's
  `shipped -> delivered` transition.
- ANY code other than `MCRT` on a `created` shipment means the parcel is moving:
  shipment `in_transit`, order `processing -> shipped` (which fires the shipped
  email with the waybill on it).
- Unknown codes update `last_scan` verbatim, are logged, and change nothing
  else. The admin panel and the customer page render the raw scan, so the
  truth is visible even while our map is behind.
- Order transitions that are no longer legal (an admin already moved it) are
  logged and skipped, never raised — the poll must survive racing a human.

Batch endpoint, measured live: `POST /track/multipleMobileShipment` with
`{"Waybill": [...]}`. Each entry carries `MobileShipmentTrackings` (the scan
list) and — once GIG has processed the parcel — a `WaybillLabel` URL, which the
poll harvests into `label_url` so labels appear without anyone pressing the
button.
"""
from __future__ import annotations

import logging

from django.utils import timezone

from apps.delivery.gig import client
from apps.delivery.models import GigShipment
from apps.orders.state import IllegalTransition, transition_by_id

logger = logging.getLogger(__name__)

BATCH_SIZE = 50
CREATED_CODES = {"MCRT", "CRT"}
DELIVERED_CODES = {"DLP"}
POLLABLE = ("created", "in_transit")


def _newest_scan(scans: list[dict]) -> dict:
    """Newest by DateTime when parseable, else the last element as sent."""
    def key(scan):
        return str(scan.get("DateTime", ""))

    try:
        return max(scans, key=key) if scans else {}
    except Exception:  # pragma: no cover - max on str never raises; belt and braces
        return scans[-1] if scans else {}


def apply_scan(shipment: GigShipment, *, code: str, scan: dict, now, label_url: str = "") -> str:
    """The state rules, shared by the poll and the webhook receiver (webhook.py).

    `code` is the GIG status code; `scan` is stored verbatim as `last_scan`
    (the poll passes a MobileShipmentTrackings entry, the webhook the decrypted
    event — both carry the Status/Location/DateTime-ish fields the UIs render).
    """
    shipment.last_scan = scan
    shipment.last_tracked_at = now
    updates = ["last_scan", "last_tracked_at", "updated_at"]
    if label_url and not shipment.label_url:
        shipment.label_url = label_url
        updates.append("label_url")

    outcome = "scan_only"
    if code in DELIVERED_CODES and shipment.status != "delivered":
        shipment.status = "delivered"
        updates.append("status")
        outcome = "delivered"
    elif code and code not in CREATED_CODES and shipment.status == "created":
        shipment.status = "in_transit"
        updates.append("status")
        outcome = "in_transit"
    elif code and code not in CREATED_CODES | DELIVERED_CODES and shipment.status == "in_transit":
        logger.info("gig scan code %r on %s (in transit)", code, shipment.waybill)

    shipment.save(update_fields=updates)

    if outcome == "in_transit":
        _move_order(shipment, "shipped", f"GIG scan {code} — parcel is moving")
    elif outcome == "delivered":
        # An order the poll never saw ship still needs the shipped hop first.
        if shipment.order.status == "processing":
            _move_order(shipment, "shipped", f"GIG scan {code}")
            shipment.order.refresh_from_db()
        _move_order(shipment, "delivered", f"GIG scan {code} — delivered")
    return outcome


def _apply(shipment: GigShipment, entry: dict, now) -> str:
    """Adapt one batch-tracking entry to apply_scan."""
    scan = _newest_scan(entry.get("MobileShipmentTrackings") or [])
    return apply_scan(
        shipment,
        code=str(scan.get("Status", "")),
        scan=scan,
        now=now,
        label_url=entry.get("WaybillLabel") or "",
    )


def _move_order(shipment: GigShipment, to_status: str, message: str) -> None:
    try:
        transition_by_id(shipment.order_id, to_status, message=message)
    except IllegalTransition as exc:
        # A human got there first (or the order is on hold). The shipment's own state
        # is already saved; the poll's job is not to argue with the order desk.
        logger.info("gig poll skipped order move for %s: %s", shipment.waybill, exc)


def poll_tracking() -> dict:
    """One pass over every pollable shipment. Returns counts for the log."""
    shipments = list(
        GigShipment.objects.filter(status__in=POLLABLE)
        .exclude(waybill="")
        .select_related("order")
    )
    counts = {"polled": 0, "in_transit": 0, "delivered": 0, "scan_only": 0}
    now = timezone.now()
    for start in range(0, len(shipments), BATCH_SIZE):
        chunk = shipments[start : start + BATCH_SIZE]
        result = client.call(
            "POST", "/track/multipleMobileShipment",
            {"Waybill": [s.waybill for s in chunk]},
        )
        data = result.data if isinstance(result.data, list) else (result.data or {}).get("data", [])
        by_waybill = {str(e.get("Waybill", "")): e for e in data or []}
        for shipment in chunk:
            entry = by_waybill.get(shipment.waybill)
            if entry is None:
                logger.info("gig poll: no tracking entry for %s", shipment.waybill)
                continue
            counts[_apply(shipment, entry, now)] += 1
            counts["polled"] += 1
    if counts["polled"]:
        logger.info("gig tracking poll: %s", counts)
    return counts
