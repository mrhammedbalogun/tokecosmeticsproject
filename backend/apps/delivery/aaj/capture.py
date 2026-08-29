"""AAJ capture — the two-step booking, one of which moves money (Plan-43).

AAJ's booking is two calls and the money sits in the second:

1. `create-booking` is FREE (docs, and measured: `paid:false`, `bookingStatus
   BOOKED`). It prices the shipment at OUR account's rate (the real cost), mints a
   `booking_id`, and is deletable until processed. A failure here changes nothing
   at AAJ that matters; a timeout MAY have created a booking we cannot find (the
   customBookingId is not searchable) — accepted litter, logged, the shipment
   stays `quoted` and the next attempt creates afresh.
2. `process-booking/{id}` CHARGES the account (credit facility or wallet) and
   mints the tracking id + label. It gets NO retries of any kind. After ANY
   non-success — refusal, 5xx, timeout — the truth is re-read from
   `get-booking/{id}` (`paid`, `shipmentId`) because MEASURED on the sandbox a 500
   "Credit facility cannot be charged" still created a shipment record with a
   label while leaving the booking unpaid. The classification:
     paid + shipmentId  → it happened: resolve to `created` (ids via get-single-shipment)
     unpaid, no shipment → nothing moved: stay `booked`, surface the refusal; retryable
     unpaid + shipment   → AAJ's half-state: `create_unconfirmed`, a human resolves
     read failed         → `create_unconfirmed` (unknown is unknown)
   The poll (tracking.py) re-runs the same read for `create_unconfirmed` rows, so a
   transient AAJ blip heals itself without anyone pressing anything.

Every ending is written to the order timeline, not just the happy one: AAJ's own
words for a refusal, the reconciled truth for an ambiguity. Audit rows are written
on 2xx only (by design), so the timeline is the only place a failed booking exists
after the container log rolls — and AAJ has no `apiId`, so their message plus the
booking id IS the lookup key their support has.

Collection (`collectionMode`) is who moves the parcel from OUR shop to AAJ: a rider
comes to us (PICKUP, our arrangement) or staff carry it to an AAJ centre (DROPOFF).
The block is UNDOCUMENTED in AAJ's Postman collection — it appears only in a
get-booking response — and was measured against the live API on 2026-08-29; see
`collection_mode()`. It does not move the price.

`AAJ_PROCESS_ENABLED` is the kill-switch on step 2: the sandbox cannot rehearse
the charge, so production runs its first booking with this off, a human checks
the DUE booking in AAJ's portal, and the runbook flips it on.

Eligibility: an admin's explicit act, on a paid (`processing`) order whose
shipment is `quoted`, `booked` (re-run step 2 only — NEVER a second create) or
`voided` (fresh booking: the void use-case is "wrong address, fix and resend").
"""
from __future__ import annotations

import logging
import re
import unicodedata
from datetime import datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils.timezone import now as django_now

from apps.core.models import Region
from apps.delivery.aaj import client
from apps.delivery.aaj.quotes import NOMINAL_BOX, address_details, weight_kg
from apps.delivery.aaj.states import state_code
from apps.delivery.models import AajShipment
from apps.orders.state import record_event

logger = logging.getLogger(__name__)

CATEGORY_CACHE_KEY = "aaj:category-id"
CATEGORY_CACHE_TTL = 24 * 60 * 60
TWO_DP = Decimal("0.01")


class CaptureRefused(Exception):
    """The step did not happen and nothing changed. `code` is machine-readable."""

    def __init__(self, code: str, detail: str):
        self.code, self.detail = code, detail
        super().__init__(detail)


class CaptureUnconfirmed(Exception):
    """process-booking MAY have charged: the follow-up read could not settle it.
    The shipment is parked in `create_unconfirmed`; nobody retries blind."""


# --- field shaping -----------------------------------------------------------------

def sanitise_name(raw: str | None, *fallbacks: str | None) -> str:
    """AAJ contact names: letters and spaces only, 2–50 chars (measured: "O'Brien-
    Smith" is a 400). Diacritics fold (Adéolá → Adeola), punctuation becomes a space
    so "O Brien Smith" stays recognisable to a rider, and the fallbacks (an email's
    local part, then a constant) are tried in turn so the rider always has a name."""
    for candidate in (raw, *fallbacks):
        if not candidate:
            continue
        folded = unicodedata.normalize("NFKD", str(candidate))
        folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
        cleaned = re.sub(r"[^A-Za-z ]+", " ", folded)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()[:50].strip()
        if len(cleaned) >= 2:
            return cleaned
    return "Customer"


def _email_local_part(email: str | None) -> str:
    return (email or "").split("@", 1)[0]


def category_id() -> str:
    """The booking category AAJ requires for DOMESTIC. Pinned by settings, else the
    "Non Electronics" row of get-categories (ids are environment-specific), cached."""
    if settings.AAJ_CATEGORY_ID:
        return settings.AAJ_CATEGORY_ID
    hit = cache.get(CATEGORY_CACHE_KEY)
    if hit:
        return hit
    result = client.call("GET", "/partner/booking/get-categories")
    data = result.data or {}
    rows = data.get("payload", data) if isinstance(data, dict) else data
    rows = rows if isinstance(rows, list) else []
    chosen = next(
        (r for r in rows if "non" in str(r.get("name", "")).lower()), None
    ) or next((r for r in rows if r.get("_id")), None)
    if not chosen or not chosen.get("_id"):
        raise CaptureRefused("no_category", "AAJ returned no booking categories — set AAJ_CATEGORY_ID.")
    cache.set(CATEGORY_CACHE_KEY, chosen["_id"], CATEGORY_CACHE_TTL)
    return chosen["_id"]


def _order_weight_g(order) -> int:
    return sum(
        (item.variant.weight_grams or 0) * item.quantity
        for item in order.items.select_related("variant")
        if item.variant
    )


def _receiver(order) -> tuple[dict, dict]:
    """(contact, addressDetails) for the order's shipping snapshot. The SNAPSHOT,
    not the live Address row: the address may have been edited since placement."""
    snap = order.shipping_address or {}
    state_name = snap.get("state") or ""
    code = state_code(state_name)
    if code is None:
        raise CaptureRefused(
            "state_unmapped",
            f"'{state_name}' is not a state AAJ can price — fix the address, then retry.",
        )
    region = Region.objects.filter(country_code="NG", level="state", name=state_name).first()
    canonical = region.name if region else state_name
    city = (snap.get("area") or snap.get("city") or canonical or "").strip()
    if len(city) < 2:
        city = canonical
    # The landmark rides WITH the street address rather than in a field of its own,
    # because AAJ's payload has no landmark field and the rider reads this line. It is
    # the whole reason the field is collected: a Nigerian street address often will not
    # take someone to the door, and "opposite Shoprite" will. Empty for older orders.
    line1 = ", ".join(
        p for p in (snap.get("line1"), snap.get("line2"), snap.get("landmark")) if p
    ) or city
    contact = {
        "name": sanitise_name(
            f"{snap.get('first_name', '')} {snap.get('last_name', '')}".strip(),
            _email_local_part(order.email),
        ),
        "phone": snap.get("phone") or order.phone or "",
        "email": order.email or "",
    }
    address = address_details(line1=line1, city=city, state_name=canonical, code=code,
                              postal=(snap.get("postcode") or "")[:20])
    return contact, address


def _sender(shipment: AajShipment) -> tuple[dict, dict]:
    """The origin SNAPSHOT the customer was quoted from (its STATE priced the zone).
    An empty snapshot (cache miss at placement) re-selects for the receiver now."""
    origin = shipment.origin or {}
    if not origin.get("state_code"):
        from apps.delivery.aaj.origins import select_origin

        snap = shipment.order.shipping_address or {}
        region = Region.objects.filter(
            country_code="NG", level="state", name=snap.get("state", "")
        ).first()

        class _Addr:  # the two fields select_origin reads
            state_region = region
            area_region = None
            latitude = snap.get("latitude")
            longitude = snap.get("longitude")

        picked = select_origin(_Addr())
        if picked is None:
            raise CaptureRefused(
                "no_origin", "No active pickup location with a resolvable state — "
                "set one up under Deliveries → Pickup locations.",
            )
        origin = picked.as_snapshot()
        shipment.origin = origin
        shipment.save(update_fields=["origin", "updated_at"])
    contact = {
        "name": sanitise_name(origin.get("name"), "Toke Cosmetics"),
        "phone": origin.get("phone") or "",
        "email": settings.AAJ_SENDER_EMAIL or settings.DEFAULT_FROM_EMAIL,
    }
    address = address_details(
        line1=origin.get("address") or origin.get("locality") or origin["state_name"],
        city=(origin.get("locality") or origin["state_name"]),
        state_name=origin["state_name"], code=origin["state_code"],
        postal=origin.get("postal_code") or settings.AAJ_SENDER_POSTAL_CODE,
    )
    return contact, address


def _pickup_date(now=None) -> datetime:
    """The day we ask AAJ's rider for, as an aware UTC datetime at the window's start.

    Same day when the capture happens before the cut-off, otherwise tomorrow; Sunday is
    pushed to Monday. Reasoned in LAGOS time (`STAFF_DISPLAY_TIMEZONE`) because "is it
    still morning?" is a question about where the shop and the rider are, not about UTC.
    Nigeria is UTC+1 with no DST, so a daytime Lagos hour never lands on a different UTC
    calendar date — the day AAJ reads is the day the packer meant whichever way they
    parse it.

    AAJ validates NONE of this (measured 2026-08-29: a `pickupDate` of 2020-01-01 was
    accepted with a 201), so a wrong date here is silent. Hence the Sunday push and the
    cut-off live in code rather than in a hope about their side.
    """
    lagos = ZoneInfo(settings.STAFF_DISPLAY_TIMEZONE)
    local = (now or django_now()).astimezone(lagos)
    day = local.date()
    if local.hour >= settings.AAJ_PICKUP_CUTOFF_HOUR:
        day += timedelta(days=1)
    if day.weekday() == 6:  # Sunday — no rider; ask for Monday
        day += timedelta(days=1)
    start = time.fromisoformat(settings.AAJ_PICKUP_WINDOW_FROM)
    return datetime.combine(day, start, tzinfo=lagos).astimezone(ZoneInfo("UTC"))


def collection_mode(now=None) -> dict:
    """`collectionMode` for create-booking — who moves the parcel from OUR shop to AAJ.

    UNDOCUMENTED: AAJ's Postman collection shows this block only inside a get-booking
    response, never in the create-booking request. Measured against the live API on
    2026-08-29: create-booking accepts it and echoes it back, `collectionType` takes
    exactly PICKUP or DROPOFF (their spelling), `pickupDetails` is optional but its
    `pickupTimeRange` is required once `pickupDetails` is present, and the total is
    unchanged at ₦5,100 either way — so switching collection never re-prices a customer
    who was quoted through `/quote`.

    Whether AAJ ACTS on it — dispatches a rider — is not something their API can tell
    us; that is confirmed with AAJ, and until it is, staff should not assume a rider is
    coming. `AAJ_COLLECTION_TYPE=DROPOFF` reverts to staff carrying parcels in.
    """
    kind = (settings.AAJ_COLLECTION_TYPE or "PICKUP").strip().upper()
    if kind != "PICKUP":
        return {"collectionType": "DROPOFF"}
    stamp = _pickup_date(now).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return {
        "collectionType": "PICKUP",
        "pickupDetails": {
            "pickupDate": stamp,
            "pickupTimeRange": {
                "from": settings.AAJ_PICKUP_WINDOW_FROM,
                "to": settings.AAJ_PICKUP_WINDOW_TO,
            },
        },
    }


def booking_body(shipment: AajShipment) -> dict:
    order = shipment.order
    receiver_contact, receiver_address = _receiver(order)
    sender_contact, sender_address = _sender(shipment)
    declared = Decimal(order.subtotal).quantize(TWO_DP)
    return {
        "sender": {"contact": sender_contact, "addressDetails": sender_address},
        "receiver": {"contact": receiver_contact, "addressDetails": receiver_address},
        "packageInsurance": "FR",  # customers pay us; we are not buying cover from AAJ
        "packages": {
            "packageType": "regular",
            "itemsValue": float(declared),
            "packages": [{
                "unitMeasurement": "KGS",
                "actualWeight": weight_kg(_order_weight_g(order)),
                "packageDimension": NOMINAL_BOX,
                "items": [{
                    "name": f"Cosmetics order {order.number}",
                    "quantity": 1,
                    "unitMeasurement": "PCS",
                    "price": float(declared),
                }],
            }],
            "addOns": [],
            "createMultiple": False,
        },
        "payments": {
            "accountNumber": settings.AAJ_ACCOUNT_NUMBER,
            "transaction": {"generateTransaction": True, "method": settings.AAJ_PAYMENT_METHOD},
        },
        "collectionMode": collection_mode(),
        "carrier": "AAJ",
        "serviceType": "DOMESTIC",
        "deliveryMode": "DOOR_STEP",
        "description": f"Cosmetics order {order.number}",
        "isDraft": False,
        "category": category_id(),
        "customBookingId": order.number,
        "getAcknowledgementCopy": False,
    }


# --- the two steps -----------------------------------------------------------------

def _eligible(order, shipment: AajShipment) -> None:
    if shipment.status not in AajShipment.CAPTURABLE:
        raise CaptureRefused(
            "wrong_state",
            f"Shipment is '{shipment.status}' — only quoted, booked or voided can be captured.",
        )
    if order.status != "processing":
        raise CaptureRefused(
            "order_not_paid",
            f"Order is '{order.status}' — capture only after payment (processing).",
        )
    if not settings.AAJ_ACCOUNT_NUMBER:
        raise CaptureRefused("not_configured", "AAJ_ACCOUNT_NUMBER is not set.")


def _create_booking(shipment: AajShipment, *, actor) -> None:
    order = shipment.order
    body = booking_body(shipment)
    previous = (shipment.booking_id, shipment.tracking_id)
    try:
        result = client.call("POST", "/partner/booking/create-booking", body, retries=0)
    except client.AajUnavailable as exc:
        # FREE step: a booking may now exist at AAJ that we cannot find. Litter,
        # not money — say so in the timeline and leave the shipment capturable.
        record_event(order, "aaj", actor=actor,
                     message="AAJ create-booking timed out — nothing charged; a stray DUE "
                             "booking may exist in AAJ's portal. Safe to retry.")
        raise CaptureRefused("create_timeout", f"AAJ did not answer: {exc}. Nothing was charged; retry.")
    except client.AajError as exc:
        # A validation refusal (a name AAJ's rules reject, an address field): nothing
        # exists at AAJ, nothing charged. Surfaced verbatim so the desk can fix the cause —
        # and RECORDED for the same reason the GIG lane records its refusals: the audit
        # table writes on 2xx only (core/audit.py), so without this line the reason lives
        # in a container log that dies at the next deploy, and a day later nobody can say
        # why the order is still unbooked.
        record_event(order, "aaj", actor=actor,
                     message=f"AAJ refused the booking: {exc}. Nothing was charged.")
        raise CaptureRefused("create_rejected", f"AAJ refused the booking: {exc}. Nothing was charged.")
    data = result.data or {}
    booking = data.get("booking") or {}
    booking_id = str(booking.get("_id") or booking.get("id") or "")
    if not booking_id:
        record_event(order, "aaj", actor=actor,
                     message="AAJ accepted the booking but returned no booking id — nothing "
                             "was charged, and any booking it made is unreachable by id.")
        raise CaptureRefused("no_booking_id", "AAJ answered without a booking id.")
    quote = data.get("quote") or {}
    raw_cost = quote.get("total", booking.get("totalAmount"))
    cost = Decimal(str(raw_cost)).quantize(TWO_DP) if raw_cost is not None else None

    with transaction.atomic():
        shipment.status = "booked"
        shipment.booking_id = booking_id
        shipment.cost = cost
        shipment.tracking_id = ""
        shipment.aaj_shipment_id = ""
        shipment.label_url = ""
        shipment.last_scan = {}
        shipment.last_status = None
        shipment.save(update_fields=[
            "status", "booking_id", "cost", "tracking_id", "aaj_shipment_id",
            "label_url", "last_scan", "last_status", "updated_at",
        ])
        note = ""
        if previous[1]:
            note = f" (replaces voided shipment {previous[1]}, booking {previous[0]})"
        margin = ""
        if cost is not None and shipment.charged is not None:
            delta = Decimal(shipment.charged) - cost
            margin = f"; customer paid ₦{shipment.charged}, margin ₦{delta}"
            if delta < 0:
                logger.warning("aaj cost exceeds what the customer paid on %s: cost %s charged %s",
                               order.number, cost, shipment.charged)
        record_event(order, "aaj", actor=actor,
                     message=f"AAJ booking {booking_id} created at ₦{cost}{margin} — not yet "
                             f"charged{note}.")


def _resolve_created(shipment: AajShipment, *, tracking_id: str, label_url: str,
                     aaj_shipment_id: str, actor, how: str) -> None:
    order = shipment.order
    with transaction.atomic():
        shipment.status = "created"
        shipment.tracking_id = tracking_id
        shipment.aaj_shipment_id = aaj_shipment_id or shipment.aaj_shipment_id
        if label_url:
            shipment.label_url = label_url
        shipment.save(update_fields=[
            "status", "tracking_id", "aaj_shipment_id", "label_url", "updated_at",
        ])
        order.tracking_carrier = "AAJ"
        order.tracking_number = tracking_id
        order.save(update_fields=["tracking_carrier", "tracking_number", "updated_at"])
        record_event(order, "aaj", actor=actor,
                     message=f"AAJ shipment {tracking_id} created (₦{shipment.cost} charged to "
                             f"the AAJ account, booking {shipment.booking_id}){how}.")


def _label_from(docs) -> str:
    for doc in docs or []:
        url = doc.get("url") if isinstance(doc, dict) else doc
        if isinstance(url, str) and url.startswith("http"):
            return url
    return ""


def read_booking(booking_id: str) -> dict:
    """get-booking, flattened to the booking record (`foundBooking` after processing,
    `booking` before — measured both shapes)."""
    result = client.call("GET", f"/partner/booking/get-booking/{booking_id}")
    data = result.data or {}
    if isinstance(data, dict):
        return data.get("foundBooking") or data.get("booking") or data
    return {}


def read_shipment(identifier: str) -> dict:
    result = client.call("GET", f"/partner/shipment/get-single-shipment/{identifier}")
    return result.data if isinstance(result.data, dict) else {}


def reconcile(shipment: AajShipment, *, actor=None, how: str = "") -> str:
    """Settle a `booked`/`create_unconfirmed` shipment against AAJ's records.
    Returns the outcome: "created" | "booked" | "unconfirmed". READS ONLY."""
    try:
        booking = read_booking(shipment.booking_id)
    except client.AajError as exc:
        logger.warning("aaj reconcile read failed for %s: %s", shipment.booking_id, exc)
        return _park_unconfirmed(shipment, actor=actor, why=f"get-booking failed: {exc}")
    paid = bool(booking.get("paid"))
    shipment_id = str(booking.get("shipmentId") or "")
    if paid and shipment_id:
        try:
            record = read_shipment(shipment_id)
        except client.AajError as exc:
            return _park_unconfirmed(shipment, actor=actor,
                                     why=f"paid but get-single-shipment failed: {exc}")
        tracking_id = str(record.get("trackingId") or "")
        if not tracking_id:
            return _park_unconfirmed(shipment, actor=actor, why="paid but no tracking id readable")
        _resolve_created(shipment, tracking_id=tracking_id,
                         label_url=_label_from(record.get("labelDocuments")),
                         aaj_shipment_id=shipment_id, actor=actor, how=how)
        return "created"
    if not paid and not shipment_id:
        if shipment.status != "booked":
            shipment.status = "booked"
            shipment.save(update_fields=["status", "updated_at"])
            record_event(shipment.order, "aaj", actor=actor,
                         message=f"AAJ booking {shipment.booking_id} confirmed UNPAID and "
                                 "without a shipment — safe to retry the charge.")
        return "booked"
    return _park_unconfirmed(
        shipment, actor=actor,
        why=f"booking unpaid but AAJ holds shipment record {shipment_id} (their half-state)",
    )


def _park_unconfirmed(shipment: AajShipment, *, actor, why: str) -> str:
    if shipment.status != "create_unconfirmed":
        shipment.status = "create_unconfirmed"
        shipment.save(update_fields=["status", "updated_at"])
        record_event(shipment.order, "aaj", actor=actor,
                     message=f"AAJ charge UNCONFIRMED for booking {shipment.booking_id}: {why}. "
                             "Check AAJ's portal before any retry.")
    logger.error("aaj capture unconfirmed for %s: %s", shipment.order.number, why)
    return "unconfirmed"


def _process_booking(shipment: AajShipment, *, actor) -> None:
    order = shipment.order
    if not settings.AAJ_PROCESS_ENABLED:
        raise CaptureRefused(
            "process_disabled",
            f"Booking {shipment.booking_id} is created but NOT charged: AAJ_PROCESS_ENABLED "
            "is off. Flip it on after the first controlled live booking (runbook).",
        )
    failure: Exception | None = None
    try:
        result = client.call(
            "POST", f"/partner/booking/process-booking/{shipment.booking_id}", retries=0
        )
    except client.AajError as exc:  # AajUnavailable included — every non-success reconciles
        failure = exc
    else:
        payload = (result.data or {}).get("payload") or {}
        record = payload.get("shipment") or {}
        tracking_id = str(record.get("tracking_id") or record.get("trackingId") or "")
        if tracking_id:
            _resolve_created(shipment, tracking_id=tracking_id,
                             label_url=_label_from(record.get("labelDocuments")),
                             aaj_shipment_id=str(record.get("_id") or ""), actor=actor, how="")
            return
        failure = CaptureRefused("no_tracking_id", "AAJ processed without a tracking id.")

    logger.warning("aaj process-booking failed for %s: %s — reconciling", order.number, failure)
    outcome = reconcile(shipment, actor=actor, how=" (resolved from AAJ's records after a failed answer)")
    if outcome == "created":
        return
    if outcome == "booked":
        # reconcile() writes the STATE ("confirmed unpaid, safe to retry") and only when
        # the state actually moved — so on a re-run from `booked` it writes nothing at
        # all. The REASON is this line's job, and the reason is the half a person acts
        # on: "Credit facility cannot be charged" is a call to AAJ, not a retry.
        record_event(order, "aaj", actor=actor,
                     message=f"AAJ refused the charge on booking {shipment.booking_id}: "
                             f"{failure}. Nothing was charged (verified against AAJ's records).")
        raise CaptureRefused(
            "process_refused",
            f"AAJ refused the charge: {failure}. Nothing was charged; fix the account/"
            "credit with AAJ and retry.",
        )
    raise CaptureUnconfirmed(str(failure))


def capture_shipment(order, *, actor) -> AajShipment:
    """Create (if needed) then process. See the module docstring for the rules."""
    shipment = AajShipment.objects.filter(order=order).select_related("order").first()
    if shipment is None:
        raise CaptureRefused("not_aaj", "This order has no AAJ shipment.")
    _eligible(order, shipment)
    if shipment.status in ("quoted", "voided"):
        _create_booking(shipment, actor=actor)
    _process_booking(shipment, actor=actor)
    return shipment


def check_unconfirmed(order, *, actor) -> str:
    """The admin's "Check with AAJ" act on a `create_unconfirmed` (or `booked`)
    shipment — reconcile only, never process."""
    shipment = AajShipment.objects.filter(order=order).select_related("order").first()
    if shipment is None:
        raise CaptureRefused("not_aaj", "This order has no AAJ shipment.")
    if shipment.status not in ("create_unconfirmed", "booked") or not shipment.booking_id:
        raise CaptureRefused("wrong_state", f"Nothing to check: shipment is '{shipment.status}'.")
    return reconcile(shipment, actor=actor, how=" (resolved by a staff check)")


# --- after creation ----------------------------------------------------------------

VOIDABLE_SCANS = {"", "LABEL_CREATED", "PICKUP_SCAN"}


def can_void(shipment: AajShipment) -> tuple[bool, str]:
    """Void is allowed by AAJ until the first hub scan (status 1 Received IS one).
    `created` always qualifies; `in_transit` only while the newest scan is still
    pre-hub. AAJ's own refusal is the final word — this is the UI's hint."""
    if shipment.status == "created":
        return True, ""
    if shipment.status == "in_transit":
        scan = str((shipment.last_scan or {}).get("scanType") or "")
        if scan in VOIDABLE_SCANS:
            return True, ""
        return False, f"AAJ has already scanned it ({scan}) — void is refused after the first hub scan"
    return False, f"shipment is {shipment.status}"


def void_shipment(order, *, actor) -> AajShipment:
    """Reverse a created shipment (and its pending charge) with AAJ. `orders.manage`
    — it reverses money. The order's generic tracking fields are cleared so the
    customer page stops showing a live-looking line for a dead shipment."""
    shipment = AajShipment.objects.filter(order=order).select_related("order").first()
    if shipment is None:
        raise CaptureRefused("not_aaj", "This order has no AAJ shipment.")
    ok, why = can_void(shipment)
    if not ok:
        raise CaptureRefused("not_voidable", why)
    key = shipment.tracking_id or shipment.aaj_shipment_id
    if not key:
        raise CaptureRefused("no_tracking_id", "No AAJ shipment id to void.")
    result = client.call("DELETE", f"/partner/shipment/void-shipment/{key}",
                         {"unrestricted": False}, retries=0)
    order = shipment.order  # freshly loaded above; the caller's instance may be stale
    with transaction.atomic():
        shipment.status = "voided"
        shipment.save(update_fields=["status", "updated_at"])
        if order.tracking_carrier == "AAJ" and order.tracking_number == shipment.tracking_id:
            order.tracking_carrier = ""
            order.tracking_number = ""
            order.save(update_fields=["tracking_carrier", "tracking_number", "updated_at"])
        record_event(order, "aaj", actor=actor,
                     message=f"AAJ shipment {shipment.tracking_id} VOIDED (booking "
                             f"{shipment.booking_id}, ₦{shipment.cost} to be reversed): "
                             f"{result.message}. Capture again to rebook.")
    return shipment


def fetch_label(shipment: AajShipment) -> str | None:
    """The label PDF URL. AAJ issues it AT process time (it rode in the process
    response), so this is the fallback read for rows resolved without one."""
    if not shipment.tracking_id:
        raise CaptureRefused("no_tracking_id", "No AAJ shipment yet — capture first.")
    if shipment.label_url:
        return shipment.label_url
    record = read_shipment(shipment.tracking_id)
    url = _label_from(record.get("labelDocuments"))
    if url:
        shipment.label_url = url
        shipment.save(update_fields=["label_url", "updated_at"])
        return url
    return None
