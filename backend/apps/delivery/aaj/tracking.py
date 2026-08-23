"""The AAJ tracking poll (Plan-43). Pull only — AAJ has no webhooks (their docs
say "consider webhooks" in five places and document none; their track page says
"poll until status reaches 4").

AAJ's status vocabulary IS published and was measured across 107 sandbox
shipments (plan doc §2): numeric `status` 0 Pending/label created, 1 Received,
2 In Transit, 3 Out For Delivery, 4 Delivered, 5 Exception, 6 Available for
pickup, 7 Voided, 8 Returned, 9 Undergoing clearance, 12 Reweighed; `events[]`
carry a `scanType` (LABEL_CREATED, ORIGIN_SCAN, ARRIVAL_SCAN, DEPARTURE_SCAN,
OUTBOUND_SCAN, DELIVERY_SCAN, EXCEPTION_SCAN, RETURN_SCAN, REWEIGH_SCAN…). The
rules:

- 4 moves the shipment to `delivered` and attempts the order's `shipped ->
  delivered` transition (with the `processing -> shipped` hop first if the poll
  never saw it move — the GIG rule).
- Any movement code (1, 2, 3, 6, 9, 10, 11, 12) on a `created` shipment means
  the parcel is moving: shipment `in_transit`, order `processing -> shipped`
  (which fires the shipped email with the tracking id on it).
- 7 (voided at AAJ's end) and 8 (returned) are TERMINAL for the poll: the
  shipment stops polling, staff are emailed, the ORDER is not moved — what to do
  with a returned parcel is a refund-direction decision for a human. A void also
  clears the order's generic tracking fields so the customer page stops showing
  a live-looking line for a dead shipment.
- 5 (exception) and 12 (reweighed — AAJ may bill the difference) change no
  status but email staff the FIRST time they appear.
- Unknown codes update `last_scan` verbatim, are logged, and change nothing else.
- Order transitions that are no longer legal (an admin already moved it) are
  logged and skipped, never raised — the poll must survive racing a human.
- One GET per shipment (no batch endpoint), a short timeout, and the pass STOPS
  at the first unreachable answer: an outage must cost one call, not N × 15 s.
"""
from __future__ import annotations

import logging

from django.utils import timezone

from apps.delivery.aaj import client
from apps.delivery.models import AajShipment
from apps.orders.state import IllegalTransition, transition_by_id

logger = logging.getLogger(__name__)

POLL_TIMEOUT_SECONDS = 8.0
POLLABLE = ("created", "in_transit")

STATUS_LABELS = {
    0: "Pending (label created)", 1: "Received", 2: "In transit", 3: "Out for delivery",
    4: "Delivered", 5: "Exception", 6: "Available for pickup", 7: "Voided", 8: "Returned",
    9: "Undergoing clearance", 10: "Ready for export", 11: "Departed", 12: "Reweighed",
}
DELIVERED = {4}
MOVING = {1, 2, 3, 6, 9, 10, 11, 12}
VOIDED = {7}
RETURNED = {8}
ATTENTION = {5, 12}  # no status change; staff told on first appearance


def _newest_event(events: list) -> dict:
    """Newest by dateTime when parseable, else the last element as sent."""
    rows = [e for e in (events or []) if isinstance(e, dict)]
    if not rows:
        return {}
    try:
        return max(rows, key=lambda e: str(e.get("dateTime", "")))
    except Exception:  # pragma: no cover
        return rows[-1]


def _notify(shipment: AajShipment, reason: str, description: str) -> None:
    from apps.notifications.staff import notify_staff

    try:
        notify_staff("delivery.aaj_attention", {
            "order_number": shipment.order.number,
            "tracking_id": shipment.tracking_id,
            "reason": reason,
            "description": description,
            "status_label": STATUS_LABELS.get(shipment.last_status, str(shipment.last_status)),
        })
    except Exception as exc:  # the poll must outlive a broker blip
        logger.warning("aaj attention notify failed for %s: %s", shipment.tracking_id, exc)


def apply_status(shipment: AajShipment, *, code, scan: dict, now, label_url: str = "") -> str:
    """The state rules, shared by the poll and any future push receiver."""
    previous = shipment.last_status
    shipment.last_scan = scan
    shipment.last_tracked_at = now
    shipment.last_status = code if isinstance(code, int) else None
    updates = ["last_scan", "last_tracked_at", "last_status", "updated_at"]
    if label_url and not shipment.label_url:
        shipment.label_url = label_url
        updates.append("label_url")

    outcome = "scan_only"
    if code in DELIVERED and shipment.status != "delivered":
        shipment.status, outcome = "delivered", "delivered"
        updates.append("status")
    elif code in VOIDED and shipment.status != "voided":
        shipment.status, outcome = "voided", "voided"
        updates.append("status")
    elif code in RETURNED and shipment.status != "returned":
        shipment.status, outcome = "returned", "returned"
        updates.append("status")
    elif code in MOVING and shipment.status == "created":
        shipment.status, outcome = "in_transit", "in_transit"
        updates.append("status")
    elif isinstance(code, int) and code not in STATUS_LABELS:
        logger.info("aaj unknown status %r on %s", code, shipment.tracking_id)
    shipment.save(update_fields=updates)

    description = str(scan.get("description") or "")
    if outcome == "in_transit":
        _move_order(shipment, "shipped", f"AAJ scan {STATUS_LABELS.get(code, code)} — parcel is moving")
    elif outcome == "delivered":
        if shipment.order.status == "processing":
            _move_order(shipment, "shipped", "AAJ scan — delivered (shipped hop first)")
            shipment.order.refresh_from_db()
        _move_order(shipment, "delivered", "AAJ scan — delivered")
    elif outcome == "voided":
        order = shipment.order
        if order.tracking_carrier == "AAJ" and order.tracking_number == shipment.tracking_id:
            order.tracking_carrier = ""
            order.tracking_number = ""
            order.save(update_fields=["tracking_carrier", "tracking_number", "updated_at"])
        _notify(shipment, "voided at AAJ's end", description)
    elif outcome == "returned":
        _notify(shipment, "returned to sender", description)
    if code in ATTENTION and previous != code:
        _notify(shipment, STATUS_LABELS[code].lower(), description)
    return outcome


def _move_order(shipment: AajShipment, to_status: str, message: str) -> None:
    try:
        transition_by_id(shipment.order_id, to_status, message=message)
    except IllegalTransition as exc:
        # A human got there first (or the order is on hold). The shipment's own state
        # is already saved; the poll's job is not to argue with the order desk.
        logger.info("aaj poll skipped order move for %s: %s", shipment.tracking_id, exc)


def track_one(shipment: AajShipment, now) -> str:
    result = client.call(
        "GET", f"/partner/shipment/track-shipment/{shipment.tracking_id}?extraDetails=false",
        timeout=POLL_TIMEOUT_SECONDS, retries=0,
    )
    data = result.data if isinstance(result.data, dict) else {}
    code = data.get("status")
    scan = _newest_event(data.get("events") or [])
    if not scan:
        scan = {"status": code, "description": data.get("description", ""),
                "dateTime": data.get("timestamp", "")}
    return apply_status(shipment, code=code, scan=scan, now=now)


def poll_tracking() -> dict:
    """One pass over every pollable shipment, plus a reconcile read for every
    `create_unconfirmed` row. Returns counts for the log."""
    from apps.delivery.aaj.capture import reconcile

    counts = {"polled": 0, "in_transit": 0, "delivered": 0, "voided": 0, "returned": 0,
              "scan_only": 0, "reconciled": 0, "stopped": False}
    now = timezone.now()
    pending = list(
        AajShipment.objects.filter(status="create_unconfirmed").exclude(booking_id="")
        .select_related("order")
    )
    for shipment in pending:
        try:
            outcome = reconcile(shipment, how=" (resolved by the tracking poll)")
        except client.AajUnavailable as exc:
            logger.warning("aaj poll stopped at reconcile: %s", exc)
            counts["stopped"] = True
            return counts
        if outcome != "unconfirmed":
            counts["reconciled"] += 1

    shipments = list(
        AajShipment.objects.filter(status__in=POLLABLE).exclude(tracking_id="")
        .select_related("order")
    )
    for shipment in shipments:
        try:
            counts[track_one(shipment, now)] += 1
            counts["polled"] += 1
        except client.AajUnavailable as exc:
            logger.warning("aaj poll stopped: %s", exc)
            counts["stopped"] = True
            break
        except client.AajError as exc:
            logger.info("aaj poll: %s for %s", exc, shipment.tracking_id)
    if counts["polled"] or counts["reconciled"]:
        logger.info("aaj tracking poll: %s", counts)
    return counts
