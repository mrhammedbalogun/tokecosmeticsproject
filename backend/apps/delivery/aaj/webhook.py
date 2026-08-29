"""AAJ tracking webhook — authenticate one pushed event and apply it (Plan-43b).

AAJ's dashboard has a webhook URL field and issues an `aaj_`-prefixed
"HTTP Webhook Signing Key". What it does NOT come with, as of 2026-08-29, is a
published scheme: no documented header name, digest algorithm, encoding, or
payload shape (their Postman collection and curl docx mention webhooks nowhere).
So this receiver is built to work today and to LEARN the rest:

1. **A secret in the path authenticates.** `AAJ_WEBHOOK_TOKEN` is ours, not
   AAJ's — a random string we generate and paste into their dashboard as part of
   the URL. It is compared in constant time. Over TLS this is the same posture as
   a GitHub-style secret URL, and it is what makes the endpoint usable before
   their signature scheme is known. (Caveat, deliberately accepted: the path
   lands in the origin's access log, which is root-only on our box. Rotating it
   is one env change and a re-paste.)

2. **A signature, when they send one, must verify.** `verify_signature` tries
   HMAC-SHA256 and -SHA512 of the RAW body under the signing key, in hex,
   base64 and base64url, against every header whose name looks signature-ish —
   also unwrapping `sha256=…` and `t=…,v1=…` composites. A request carrying a
   signature header that matches NOTHING is rejected: holding the URL is not a
   licence to skip a check they did perform. A request with no signature header
   at all is accepted on the path token alone, and the fact is logged.

3. **An unknown shape changes nothing.** `extract_event` only reports a status
   when it finds BOTH a tracking id we know and an INTEGER code AAJ's own status
   table defines (tracking.STATUS_LABELS). Anything else is logged verbatim and
   dropped — because the alternative, guessing, moves ORDERS: a wrong "4" marks
   a customer's order delivered. The 2-hourly poll remains the source of truth
   and the fallback for anything this drops, exactly as it is for GIG.

The first real delivery is therefore a specimen: `logger.info` records which
header and encoding matched (or that none did) and the whole payload, which is
what turns the tolerance above into a pinned scheme.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Header names are matched case-insensitively; a name is a candidate if it
# contains one of these. Kept as substrings because we do not know theirs.
_SIGNATURE_HINTS = ("signature", "signed", "hmac", "digest", "hash")
# Headers a proxy adds that contain "digest"/"hash" but are never a body HMAC.
_SIGNATURE_SKIP = ("content-digest", "want-digest", "repr-digest", "if-none-match")

MAX_BODY_LOG = 4000


class InvalidWebhookPayload(Exception):
    """The request did not authenticate, or its body is not JSON."""


def _digests(body: bytes, key: str) -> set[str]:
    """Every digest string this body could legitimately produce under `key`."""
    out: set[str] = set()
    for algo in (hashlib.sha256, hashlib.sha512):
        mac = hmac.new(key.encode(), body, algo).digest()
        out.add(mac.hex())
        out.add(base64.b64encode(mac).decode())
        out.add(base64.urlsafe_b64encode(mac).decode().rstrip("="))
    return out


def _candidate_values(raw: str) -> list[str]:
    """The signature itself, dug out of the wrappers providers like to use:
    `sha256=<sig>`, `v1=<sig>`, `t=<ts>,v1=<sig>`, and bare."""
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
    why not — it is the line that turns the first live delivery into a spec."""
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


def _find(payload: Any, keys: tuple[str, ...]) -> Any:
    """First value under any of `keys`, at any depth (their nesting is unknown)."""
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
    """(tracking_id, status_code). Either may be empty/None — see the module note
    on why an unmappable event is dropped rather than guessed."""
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


def apply_event(payload: Any, now) -> str:
    """Apply one authenticated event. Returns what happened, for the log and the
    ack body. Never raises on an unknown shipment or an unmappable payload: AAJ
    would retry an error, and there is nothing to retry into."""
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
        # Not ours (or ours before capture stamped it) — an ack, not an error.
        logger.info("aaj webhook: unknown tracking id %s in %s", tracking_id, body)
        return "unknown_shipment"
    if code is None or code not in STATUS_LABELS:
        logger.info("aaj webhook: unmapped status %r for %s in %s", code, tracking_id, body)
        return "unmapped_status"
    scan = payload if isinstance(payload, dict) else {"payload": payload}
    outcome = apply_status(shipment, code=code, scan=scan, now=now)
    logger.info("aaj webhook: %s -> %s (%s)", tracking_id, STATUS_LABELS[code], outcome)
    return outcome
