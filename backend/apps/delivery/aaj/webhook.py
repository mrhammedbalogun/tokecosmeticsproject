"""AAJ tracking webhook — authenticate one pushed event and apply it (Plan-43b).

AAJ published the scheme on 2026-09-22 (`readme-webhook.markdown`), which turns
the tolerant receiver built in August into a pinned one. What they send:

    POST <our url>            x-aaj-signature: <hex hmac-sha256 of the RAW body>
    {"event": "scan-notification",
     "data": {"objectType": "BOOKING" | "SHIPMENT",
              "scanType": "DELIVERY_SCAN",
              "payload": { ...the whole updated object, post-scan... }}}

Three rules survive from the pre-doc version, because they are what keep a push
from moving an order it should not:

1. **A secret in the path authenticates.** `AAJ_WEBHOOK_TOKEN` is ours, not
   AAJ's — a random string we generate and paste into their dashboard as part of
   the URL. It is compared in constant time. AAJ's dashboard takes a URL and a
   signing key and nothing else, so there is no other credential to check.

2. **A signature, when they send one, must verify.** `verify_signature` checks
   the documented scheme first (hex HMAC-SHA256 of the raw body in
   `x-aaj-signature`) and still tolerates the neighbouring shapes, because their
   doc and their code have disagreed before. A request carrying a signature
   header that matches NOTHING is rejected. A request with no signature header
   is accepted on the path token alone and logged loudly — set
   `AAJ_WEBHOOK_REQUIRE_SIGNATURE=true` once a real delivery has proved they
   always sign, and unsigned pushes become 401s too.

3. **An unknown shape changes nothing.** A status is only applied when the event
   resolves to a shipment WE hold and to an INTEGER code AAJ's own status table
   defines (tracking.STATUS_LABELS). Anything else is logged verbatim and
   dropped — because the alternative, guessing, moves ORDERS: a wrong "4" marks
   a customer's order delivered. The 2-hourly poll remains the source of truth
   and the fallback for anything this drops, exactly as it is for GIG.

What the doc added:

- **BOOKING events now land.** A booking payload carries no `trackingId`, so the
  old generic extractor dropped every one of them. They are matched on
  `payload._id` (our `booking_id`) or `payload.customBookingId` (our order
  number), and — critically — their status is read from `data.scanType` ONLY.
  A booking's own `bookingState` / `orderState` / `humanStatus` are a DIFFERENT
  integer space from a shipment's `status` (their own example shows a delivered
  booking carrying `humanStatus: 0`), so reading an int off a booking would mark
  live orders with the wrong state.
- **Idempotency and ordering**, which their doc asks consumers to handle:
  a repeat of the same (object, scan, `updatedAt`) is answered without re-applying,
  and an event older than the last one we applied is logged and dropped rather
  than rewinding `last_status`.
- **`PICKUP_SCAN` on a booking is the answer to an open question**: it is AAJ
  confirming a rider collected from our shop, which is the only evidence their
  API can give that `collectionMode: PICKUP` is acted on and not just recorded.
  It gets its own log line for that reason.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
from typing import Any

from django.core.cache import cache
from django.utils.dateparse import parse_datetime

logger = logging.getLogger(__name__)

# Header names are matched case-insensitively; a name is a candidate if it
# contains one of these. `x-aaj-signature` is the documented one; the rest stay
# because their doc and their sender have disagreed before.
_SIGNATURE_HINTS = ("signature", "signed", "hmac", "digest", "hash")
# Headers a proxy adds that contain "digest"/"hash" but are never a body HMAC.
_SIGNATURE_SKIP = ("content-digest", "want-digest", "repr-digest", "if-none-match")

MAX_BODY_LOG = 4000
DEDUPE_TTL = 6 * 60 * 60  # their retry ladder is 5 attempts over minutes; 6h is slack

EVENT_FAMILY = "scan-notification"
BOOKING, SHIPMENT = "BOOKING", "SHIPMENT"

# scanType -> the numeric status in tracking.STATUS_LABELS it implies. This is the
# ONLY way a booking event gets a status (see the module note), and the fallback
# for a shipment event whose own `status` is missing or off their published table.
SCAN_STATUS = {
    "LABEL_CREATED": 0,
    "ORIGIN_SCAN": 2,
    "ARRIVAL_SCAN": 2,
    "DEPARTURE_SCAN": 2,
    "OUTBOUND_SCAN": 2,
    "PICKUP_SCAN": 2,    # the rider has the parcel — on a booking, collected from US
    "DROPOFF_SCAN": 2,   # staff carried it to an AAJ centre
    "CLEARANCE_SCAN": 9,
    "EXPORT_SCAN": 10,
    "DESTINATION_SCAN": 6,
    "DELIVERY_SCAN": 4,
    "RETURN_SCAN": 8,
    "EXCEPTION_SCAN": 5,
    "REWEIGH_SCAN": 12,
}


class InvalidWebhookPayload(Exception):
    """The request did not authenticate, or its body is not JSON."""


def _digests(body: bytes, key: str) -> set[str]:
    """Every digest string this body could legitimately produce under `key`.
    The documented one is `hashlib.sha256` + `.hex()`; the rest are tolerance."""
    out: set[str] = set()
    for algo in (hashlib.sha256, hashlib.sha512):
        mac = hmac.new(key.encode(), body, algo).digest()
        out.add(mac.hex())
        out.add(base64.b64encode(mac).decode())
        out.add(base64.urlsafe_b64encode(mac).decode().rstrip("="))
    return out


def _candidate_values(raw: str) -> list[str]:
    """The signature itself, dug out of the wrappers providers like to use:
    `sha256=<sig>`, `v1=<sig>`, `t=<ts>,v1=<sig>`, and bare (AAJ's own)."""
    values = [raw.strip()]
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if "=" in part:
            values.append(part.split("=", 1)[1].strip())
        else:
            values.append(part)
    return [v.strip().strip('"') for v in values if v.strip()]


def verify_signature(body: bytes, headers: dict, key: str) -> tuple[bool, str]:
    """(verified, how). `how` names the header and encoding that matched, or says
    why not — it is the line that proves the live scheme matches the documented one."""
    present = {
        name: value for name, value in headers.items()
        if any(h in name.lower() for h in _SIGNATURE_HINTS)
        and not any(s in name.lower() for s in _SIGNATURE_SKIP)
    }
    if not present:
        return False, "no signature header sent"
    if not key:
        return False, f"signature header(s) {sorted(present)} sent but no signing key configured"
    expected = _digests(body, key)
    for name, value in present.items():
        for candidate in _candidate_values(str(value)):
            for digest in expected:
                if hmac.compare_digest(candidate, digest):
                    return True, f"{name} matched"
    return False, f"signature header(s) {sorted(present)} matched nothing"


def parse_body(body: bytes) -> Any:
    try:
        return json.loads(body.decode("utf-8", errors="replace") or "null")
    except ValueError as exc:
        raise InvalidWebhookPayload(f"body is not JSON: {exc}") from exc


# --- the documented envelope -------------------------------------------------------

def read_envelope(payload: Any) -> tuple[str, str, dict] | None:
    """(objectType, scanType, the updated object) for a body in AAJ's documented
    shape, else None so the caller falls back to the tolerant extractor.

    `event` is not required to equal "scan-notification": their doc calls it a
    family label and promises more families later, and an envelope that carries an
    objectType and a dict payload is unambiguous enough to read on its own."""
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    inner = data.get("payload")
    object_type = str(data.get("objectType") or "").strip().upper()
    if not isinstance(inner, dict) or object_type not in (BOOKING, SHIPMENT):
        return None
    return object_type, str(data.get("scanType") or "").strip().upper(), inner


def _shipment_for(object_type: str, inner: dict):
    """Our AajShipment row for their updated object, or None.

    Every handle their payload offers is tried, because which ones are populated
    depends on how far the parcel has got: a shipment before capture stamped it,
    a booking whose order we can only find by `customBookingId`."""
    from apps.delivery.models import AajShipment

    rows = AajShipment.objects.select_related("order")
    oid = str(inner.get("_id") or "").strip()
    if object_type == SHIPMENT:
        tracking_id = str(inner.get("trackingId") or "").strip()
        lookups = [
            {"tracking_id": tracking_id} if tracking_id else None,
            {"aaj_shipment_id": oid} if oid else None,
            # A shipment payload names its parent booking — the handle that still
            # works when our row was parked before a tracking id was ever read.
            {"booking_id": str(inner.get("booking") or "").strip()}
            if inner.get("booking") else None,
        ]
    else:
        custom = str(inner.get("customBookingId") or "").strip()
        lookups = [
            {"booking_id": oid} if oid else None,
            {"order__number": custom} if custom else None,
        ]
    for lookup in lookups:
        if not lookup:
            continue
        found = rows.filter(**lookup).first()
        if found is not None:
            return found
    return None


def _status_for(object_type: str, scan_type: str, inner: dict) -> int | None:
    """The numeric status this event implies, or None if we will not guess one.

    A SHIPMENT carries its own `status` in the same integer space the poll reads,
    so that wins. A BOOKING does NOT: `bookingState`, `orderState` and
    `humanStatus` are a different vocabulary (their doc's delivered booking shows
    `humanStatus: 0`), so a booking is read from its scanType alone."""
    from apps.delivery.aaj.tracking import STATUS_LABELS

    if object_type == SHIPMENT:
        raw = inner.get("status")
        if isinstance(raw, bool):
            raw = None
        elif isinstance(raw, str) and raw.strip().lstrip("-").isdigit():
            raw = int(raw.strip())
        if isinstance(raw, int) and raw in STATUS_LABELS:
            return raw
    code = SCAN_STATUS.get(scan_type)
    return code if code in STATUS_LABELS else None


def _newest_event(inner: dict) -> dict:
    """The newest element of whichever event list this object keeps, so `last_scan`
    holds the same shape the poll writes (capture.can_void reads its `scanType`)."""
    rows = [
        row for key in ("events", "collectionEvents")
        for row in (inner.get(key) or []) if isinstance(row, dict)
    ]
    if not rows:
        return {}
    try:
        return max(rows, key=lambda row: str(row.get("dateTime", "")))
    except Exception:  # pragma: no cover — defensive; their rows are dicts
        return rows[-1]


def _seen_before(object_type: str, scan_type: str, inner: dict) -> bool:
    """True if this exact event was already accepted. Their doc: "Do not assume
    webhooks always arrive once" — five retry attempts, and a 200 we send after a
    slow apply can still be recorded as a timeout on their side."""
    oid = str(inner.get("_id") or "")
    stamp = str(inner.get("updatedAt") or "")
    if not oid or not stamp:
        return False  # nothing stable to key on; let apply_status' own guards hold
    key = f"aaj:webhook:{object_type}:{oid}:{scan_type}:{stamp}"
    if cache.get(key):
        return True
    cache.set(key, 1, DEDUPE_TTL)
    return False


def _is_stale(shipment, object_type: str, inner: dict) -> bool:
    """True if we already applied a LATER event for this shipment. Their doc: "Do
    not assume strict delivery order" — and apply_status writes `last_status`
    unconditionally, so a late ARRIVAL_SCAN behind a DELIVERY_SCAN would rewind it.

    Two things this refuses to do, because both would DROP a real event:
    compare across object types (a booking's `updatedAt` and its shipment's are two
    different clocks), and compare strings (their booking example ends `+01:00` and
    their shipment reads end `Z`, which sort against each other wrongly). Anything
    it cannot parse into two comparable instants is not stale."""
    last = shipment.last_scan or {}
    if str(last.get("webhook_object_type") or "") != object_type:
        return False
    stamp = parse_datetime(str(inner.get("updatedAt") or "") or " ")
    previous = parse_datetime(str(last.get("webhook_updated_at") or "") or " ")
    if stamp is None or previous is None:
        return False
    if (stamp.tzinfo is None) != (previous.tzinfo is None):
        return False  # one naive, one aware: not comparable, so not provably stale
    return stamp < previous


# --- the tolerant fallback ---------------------------------------------------------

def _find(payload: Any, keys: tuple[str, ...]) -> Any:
    """First value under any of `keys`, at any depth. Used only for a body that is
    NOT in the documented envelope — kept because their sender has not been seen
    yet and a shape we refuse to read is an event lost."""
    if isinstance(payload, dict):
        for key in keys:
            for actual, value in payload.items():
                if actual.lower().replace("_", "") == key and value not in (None, ""):
                    return value
        for value in payload.values():
            found = _find(value, keys)
            if found is not None:
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = _find(item, keys)
            if found is not None:
                return found
    return None


_TRACKING_KEYS = ("trackingid", "trackingnumber", "waybill", "tracking")
_STATUS_KEYS = ("status", "statuscode", "shipmentstatus", "trackingstatus", "code")


def extract_event(payload: Any) -> tuple[str, int | None]:
    """(tracking_id, status_code) for an undocumented body. Either may be
    empty/None — see the module note on why an unmappable event is dropped."""
    tracking = _find(payload, _TRACKING_KEYS)
    tracking_id = str(tracking).strip() if tracking is not None else ""
    raw_status = _find(payload, _STATUS_KEYS)
    code: int | None = None
    if isinstance(raw_status, bool):
        code = None
    elif isinstance(raw_status, int):
        code = raw_status
    elif isinstance(raw_status, str) and raw_status.strip().lstrip("-").isdigit():
        code = int(raw_status.strip())
    return tracking_id, code


# --- applying ----------------------------------------------------------------------

def apply_event(payload: Any, now) -> str:
    """Apply one authenticated event. Returns what happened, for the log and the
    ack body. Never raises on an unknown shipment or an unmappable payload: AAJ
    retries a non-200 up to five times, and there is nothing to retry into."""
    envelope = read_envelope(payload)
    if envelope is None:
        return _apply_untyped(payload, now)
    return _apply_documented(*envelope, payload=payload, now=now)


def _apply_documented(object_type: str, scan_type: str, inner: dict, *, payload, now) -> str:
    from apps.delivery.aaj.tracking import STATUS_LABELS, apply_status

    body = json.dumps(payload, default=str)[:MAX_BODY_LOG]
    shipment = _shipment_for(object_type, inner)
    if shipment is None:
        # Not ours (or ours before capture stamped it) — an ack, not an error.
        logger.info("aaj webhook: %s %s for an unknown object in %s", object_type, scan_type, body)
        return "unknown_shipment"
    if _seen_before(object_type, scan_type, inner):
        logger.info("aaj webhook: repeat of %s %s on %s — ignored",
                    object_type, scan_type, shipment.order.number)
        return "duplicate"
    if _is_stale(shipment, object_type, inner):
        logger.info("aaj webhook: %s %s on %s is older than the event already applied — ignored",
                    object_type, scan_type, shipment.order.number)
        return "stale"
    if scan_type == "PICKUP_SCAN" and object_type == BOOKING:
        # The only evidence AAJ's API can give that collectionMode: PICKUP is acted
        # on rather than merely recorded. See capture.collection_mode().
        logger.info("aaj webhook: PICKUP_SCAN on booking %s (%s) — a rider collected "
                    "from us, so collectionMode PICKUP is live", shipment.booking_id,
                    shipment.order.number)
    code = _status_for(object_type, scan_type, inner)
    if code is None:
        logger.info("aaj webhook: %s %s carries no status we map, on %s — nothing moved (%s)",
                    object_type, scan_type, shipment.order.number, body)
        return "unmapped_status"

    scan = dict(_newest_event(inner))
    scan.setdefault("scanType", scan_type)
    scan.setdefault("description", str(inner.get("humanStatus") or ""))
    scan["webhook_object_type"] = object_type
    scan["webhook_updated_at"] = str(inner.get("updatedAt") or "")
    label = ""
    if object_type == SHIPMENT:
        from apps.delivery.aaj.capture import label_from

        label = label_from(inner.get("labelDocuments"))
    outcome = apply_status(shipment, code=code, scan=scan, now=now, label_url=label)
    logger.info("aaj webhook: %s %s on %s -> %s (%s)", object_type, scan_type,
                shipment.order.number, STATUS_LABELS[code], outcome)
    return outcome


def _apply_untyped(payload: Any, now) -> str:
    """A body that is not in their documented envelope: the August receiver, kept
    whole. It only ever acts on a tracking id we hold plus an integer AAJ's own
    table defines, so the worst an unrecognised shape can do is nothing."""
    from apps.delivery.aaj.tracking import STATUS_LABELS, apply_status
    from apps.delivery.models import AajShipment

    tracking_id, code = extract_event(payload)
    body = json.dumps(payload, default=str)[:MAX_BODY_LOG]
    if not tracking_id:
        logger.info("aaj webhook: no tracking id in payload %s", body)
        return "no_tracking_id"
    shipment = (
        AajShipment.objects.select_related("order")
        .filter(tracking_id=tracking_id)
        .first()
    )
    if shipment is None:
        logger.info("aaj webhook: unknown tracking id %s in %s", tracking_id, body)
        return "unknown_shipment"
    if code is None or code not in STATUS_LABELS:
        logger.info("aaj webhook: unmapped status %r for %s in %s", code, tracking_id, body)
        return "unmapped_status"
    scan = payload if isinstance(payload, dict) else {"payload": payload}
    outcome = apply_status(shipment, code=code, scan=scan, now=now)
    logger.info("aaj webhook: %s -> %s (%s)", tracking_id, STATUS_LABELS[code], outcome)
    return outcome
