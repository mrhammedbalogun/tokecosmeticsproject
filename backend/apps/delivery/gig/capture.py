"""Waybill capture — the one call in this integration that moves money (Plan-32a
slice 5).

`capture/preshipment` debits the wallet the full GrandTotal and dispatches a
rider THE MOMENT it succeeds, and GIG has no cancel API. Every rule here follows
from that:

- It runs only from an admin's explicit act, on a paid (`processing`) order whose
  shipment is still `quoted`.
- The wallet is pre-checked; an insufficient or unknown-but-required balance is a
  refusal BEFORE the call, not an error after it.
- The HTTP call gets NO retries of any kind (`retry_auth=False, retries=0`
  reaches the client's structural refusal): a timeout parks the shipment in
  `create_unconfirmed`, and a HUMAN resolves it with GIG — the `apiId` logged for
  the attempt is their lookup key. Retrying a timed-out capture that actually
  succeeded would debit twice and dispatch two riders.
- Success stamps the waybill onto the shipment AND onto the order's generic
  tracking fields, so every surface that already renders tracking works unchanged.
"""
from __future__ import annotations

import logging
import urllib.parse
from decimal import Decimal

from django.conf import settings
from django.core.cache import cache
from django.db import transaction

from apps.core.models import Region
from apps.delivery.gig import client
from apps.delivery.models import GigCentre, GigShipment
from apps.orders.state import record_event

logger = logging.getLogger(__name__)

WALLET_CACHE_KEY = "gig:wallet-balance"
WALLET_CACHE_TTL = 15 * 60
TWO_DP = Decimal("0.01")


class CaptureRefused(Exception):
    """The capture did not happen and nothing changed. `code` is machine-readable."""

    def __init__(self, code: str, detail: str):
        self.code, self.detail = code, detail
        super().__init__(detail)


class CaptureUnconfirmed(Exception):
    """The capture MAY have happened: the call timed out after reaching GIG's
    direction. The shipment is parked in `create_unconfirmed`; nobody retries."""


def wallet_balance(*, refresh: bool = False):
    """GIG wallet balance as a Decimal, None when GIG doesn't report one (the
    sandbox account has no wallet record), cached 15 minutes. `refresh=True`
    bypasses the cache — capture always does."""
    if not refresh:
        hit = cache.get(WALLET_CACHE_KEY)
        if hit is not None:
            return None if hit == "unknown" else Decimal(hit)
    # The lookup is case-sensitive against GIG's stored record (measured on
    # production 2026-08-12: lowercase 200s, the issued UPPERCASE 401s
    # "Company not found." — login itself accepts either). Records are stored
    # lowercase, so normalise before asking.
    email = urllib.parse.quote(settings.GIG_EMAIL.lower())
    result = client.call("GET", f"/companyDetails/get?Email={email}")
    data = result.data.get("data", result.data) if isinstance(result.data, dict) else result.data
    record = data[0] if isinstance(data, list) and data else data if isinstance(data, dict) else {}
    raw = record.get("WalletAmount")
    balance = None if raw is None else Decimal(str(raw)).quantize(TWO_DP)
    cache.set(WALLET_CACHE_KEY, "unknown" if balance is None else str(balance), WALLET_CACHE_TTL)
    return balance


def _receiver_region(order) -> Region:
    snap = order.shipping_address or {}
    region = (
        Region.objects.filter(
            country_code="NG", level="area",
            name=snap.get("area", ""), parent__name=snap.get("state", ""),
        )
        .exclude(latitude=None)
        .first()
    )
    if region is None:
        raise CaptureRefused(
            "no_centroid",
            f"No LGA centroid for '{snap.get('area')}', {snap.get('state')} — "
            "fix the region mapping, then retry.",
        )
    return region


def _order_weight_kg(order) -> float:
    grams = sum(
        (item.variant.weight_grams or 0) * item.quantity
        for item in order.items.select_related("variant")
        if item.variant
    )
    return round(grams / 1000, 3) or 0.001


def capture_shipment(order, *, actor) -> GigShipment:
    shipment = GigShipment.objects.filter(order=order).first()
    if shipment is None:
        raise CaptureRefused("not_gig", "This order has no GIG shipment.")
    if shipment.status != "quoted":
        raise CaptureRefused(
            "wrong_state", f"Shipment is '{shipment.status}', only 'quoted' can be captured."
        )
    if order.status != "processing":
        raise CaptureRefused(
            "order_not_paid",
            f"Order is '{order.status}' — capture only after payment (processing).",
        )

    # Centre pickup vs door (32b slice 5): a shipment with a centre snapshot is a
    # pickup — the parcel travels to the CENTRE, so the receiver coordinates/address
    # come from the snapshot and the LGA region plays no part (a pickup-only LGA
    # must never be blocked by door-delivery mapping issues).
    centre_snap = shipment.centre or {}
    is_pickup = bool(centre_snap)
    if is_pickup:
        centre_id = centre_snap.get("id")
        # MEASURED (research §2g): GIG accepts ANY DestinationServiceCenterId without
        # validation and mints a waybill. This refusal is the only fence — never guess.
        if not isinstance(centre_id, int) or centre_id <= 0:
            raise CaptureRefused(
                "centre_snapshot_invalid",
                "This pickup shipment's centre snapshot is malformed — resolve with GIG "
                "support before capturing; do NOT capture as door delivery.",
            )
        pickup_lat, pickup_lng = centre_snap.get("latitude"), centre_snap.get("longitude")
        if pickup_lat is None or pickup_lng is None:
            # Old snapshot without coordinates: the live centre row is the fallback.
            live = GigCentre.objects.filter(gig_centre_id=centre_id).exclude(
                latitude=None).exclude(longitude=None).first()
            if live is None:
                raise CaptureRefused(
                    "centre_coordinates_missing",
                    "No coordinates for this pickup centre (snapshot and sync both) — "
                    "re-run the centre sync or resolve with GIG before capturing.",
                )
            pickup_lat, pickup_lng = float(live.latitude), float(live.longitude)
        region = None
    else:
        region = _receiver_region(order)
    expected_cost = Decimal(
        str((shipment.quote.get("breakdown") or {}).get("GrandTotal", 0))
    ).quantize(TWO_DP)

    # Live wallet check, never the cache: the debit is about to happen. A balance GIG
    # reports as null (sandbox, and production pre-funding) does not block — the
    # capture itself is then the check. The lookup FAILING doesn't block either: an
    # advisory pre-check must not turn a lookup outage into a capture outage. GIG's
    # own insufficient-balance refusal stays the fence.
    try:
        balance = wallet_balance(refresh=True)
    except client.GigUnavailable:
        raise  # GIG unreachable: never point a money-moving call at an API that's down
    except client.GigError as exc:
        logger.warning("gig wallet pre-check unavailable, capturing anyway: %s", exc)
        balance = None
    if balance is not None and expected_cost and balance < expected_cost:
        raise CaptureRefused(
            "wallet_insufficient",
            f"Wallet holds ₦{balance} but this shipment costs ₦{expected_cost}. "
            "Fund the GIG wallet, then retry.",
        )

    snap = order.shipping_address or {}
    if is_pickup:
        # The parcel's destination is the centre; the customer (who collects) stays
        # the named receiver so GIG's SMS/calls reach them.
        receiver_lat, receiver_lng = pickup_lat, pickup_lng
        receiver_address = centre_snap.get("address") or centre_snap.get("name") or ""
    else:
        # The snapshot pin when the customer set one (door coordinates for the rider —
        # Plan-32b ruling 2), else the LGA centroid. The SNAPSHOT, not the live Address
        # row: the address may have been edited since placement. Pair-wise on purpose —
        # half a pin (impossible via the serializer, but snapshots outlive rules) must
        # never mix a pin latitude with a centroid longitude.
        receiver_lat, receiver_lng = snap.get("latitude"), snap.get("longitude")
        if receiver_lat is None or receiver_lng is None:
            receiver_lat, receiver_lng = float(region.latitude), float(region.longitude)
        # Landmark sits straight after the street lines, before the area/state, because
        # that is the order a person reads a Nigerian address in and GIG has no field
        # of its own for it. It is why the field is collected at all — see the model.
        receiver_address = ", ".join(
            part for part in (
                snap.get("line1"), snap.get("line2"), snap.get("landmark"),
                snap.get("area"), snap.get("state"),
            )
            if part
        )
    receiver_name = f"{snap.get('first_name', '')} {snap.get('last_name', '')}".strip() or order.email
    # Sender = the origin SNAPSHOT the customer was quoted from (Plan-34), all-or-
    # nothing on the coordinate pair — a snapshot without both coords must never
    # mix its address with the env pin (same pairing discipline as the receiver
    # pin above). Empty/partial snapshot = the env origin: pre-Plan-34 shipments
    # and the zero-rows fallback, which is exactly what they were priced from.
    origin_snap = shipment.origin or {}
    if origin_snap.get("latitude") is not None and origin_snap.get("longitude") is not None:
        sender = {
            "SenderName": origin_snap.get("name") or settings.GIG_SENDER_NAME,
            "SenderPhoneNumber": origin_snap.get("phone") or settings.GIG_SENDER_PHONE,
            "SenderAddress": origin_snap.get("address", ""),
            "InputtedSenderAddress": origin_snap.get("address", ""),
            "SenderLocality": origin_snap.get("locality", ""),
            "SenderLocation": {
                "Latitude": origin_snap["latitude"],
                "Longitude": origin_snap["longitude"],
            },
        }
    else:
        sender = {
            "SenderName": settings.GIG_SENDER_NAME,
            "SenderPhoneNumber": settings.GIG_SENDER_PHONE,
            "SenderAddress": settings.GIG_SENDER_ADDRESS,
            "InputtedSenderAddress": settings.GIG_SENDER_ADDRESS,
            "SenderLocality": settings.GIG_SENDER_LOCALITY,
            "SenderLocation": {
                "Latitude": settings.GIG_SENDER_LATITUDE,
                "Longitude": settings.GIG_SENDER_LONGITUDE,
            },
        }
    body = {
        "SenderDetails": sender,
        "ReceiverDetails": {
            "ReceiverName": receiver_name,
            "ReceiverPhoneNumber": snap.get("phone") or order.phone or "",
            "ReceiverAddress": receiver_address,
            "InputtedReceiverAddress": receiver_address,
            "ReceiverLocation": {"Latitude": receiver_lat, "Longitude": receiver_lng},
            # MEASURED shape (research §2g): this field — HERE, in ReceiverDetails —
            # is what makes the shipment a centre pickup ("PickupOptions":
            # "SERVICECENTER" on the tracked shipment). Every other placement, or a
            # PickUpOptions flag in any spelling, is a Joi 400.
            **({"DestinationServiceCenterId": centre_snap["id"]} if is_pickup else {}),
        },
        "ShipmentDetails": {
            "VehicleType": settings.GIG_VEHICLE_TYPE,
            "IsCashOnDelivery": False,  # settled: customers pay upfront, always
        },
        "ShipmentItems": [{
            "ItemName": f"Cosmetics order {order.number}",
            "Quantity": 1,
            "Weight": _order_weight_kg(order),
            "ShipmentType": 1,
            "Value": float(order.subtotal),
            "IsVolumetric": False,
        }],
    }

    try:
        result = client.call(
            "POST", "/capture/preshipment", body, retry_auth=False, retries=0
        )
    except client.GigUnavailable as exc:
        shipment.status = "create_unconfirmed"
        shipment.save(update_fields=["status", "updated_at"])
        record_event(order, "gig", actor=actor,
                     message="Waybill capture TIMED OUT — status unconfirmed, check with GIG "
                             "before any retry.")
        logger.error("gig capture unconfirmed for %s: %s", order.number, exc)
        raise CaptureUnconfirmed(str(exc)) from exc

    waybill = str((result.data or {}).get("Waybill", ""))
    if not waybill:
        raise CaptureRefused(
            "no_waybill", f"GIG answered without a waybill (apiId {result.api_id})."
        )

    with transaction.atomic():
        shipment.status = "created"
        shipment.waybill = waybill
        shipment.capture_api_id = result.api_id
        shipment.cost = expected_cost or None
        shipment.save(update_fields=["status", "waybill", "capture_api_id", "cost", "updated_at"])
        order.tracking_carrier = "GIG"
        order.tracking_number = waybill
        order.save(update_fields=["tracking_carrier", "tracking_number", "updated_at"])
        record_event(order, "gig", actor=actor,
                     message=f"GIG waybill {waybill} created (₦{expected_cost} from wallet, "
                             f"apiId {result.api_id}).")
    cache.delete(WALLET_CACHE_KEY)  # the balance just changed
    return shipment


def fetch_label(shipment: GigShipment):
    """The waybill label PDF URL, or None while GIG hasn't processed the parcel yet
    ("Shipment Details Not Found" until it passes through their station — measured,
    and confirmed by their developer). None is a normal state, not an error."""
    if not shipment.waybill:
        raise CaptureRefused("no_waybill", "No waybill yet — capture first.")
    try:
        result = client.call("POST", "/invoice/generate", {"Waybill": shipment.waybill})
    except client.GigError as exc:
        if isinstance(exc, client.GigUnavailable):
            raise
        logger.info("gig label not ready for %s: %s", shipment.waybill, exc)
        return None
    data = result.data
    url = data if isinstance(data, str) else next(
        (v for v in (data or {}).values() if isinstance(v, str) and v.startswith("http")), ""
    ) if isinstance(data, dict) else ""
    if url:
        shipment.label_url = url
        shipment.save(update_fields=["label_url", "updated_at"])
        return url
    return None
