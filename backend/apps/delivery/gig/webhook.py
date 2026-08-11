"""GIG tracking webhook — decrypt and apply one pushed event.

GIG's webhook scheme (their Notion "Webhooks Documentation", fetched 2026-08-11,
mirrored in docs/gigimplementationresearch.md §2f): we register a URL via
`POST {GIG_WEBHOOK_API_BASE}/api/webhook/add-webhook-user` (the
`register_gig_webhook` management command) and receive a per-account `secret`.
Events then arrive as a POST whose body is ONE base64 string:

    base64( salt[16] + iv[16] + AES-256-CBC(ciphertext) )

with the AES key derived as PBKDF2-HMAC-SHA1(secret, salt, 10000 iterations,
32 bytes) — the scheme their published .NET/Node samples implement. Successful
decryption with our secret IS the authentication: there is no signature header,
so a payload that decrypts to valid JSON can only have been encrypted by a
holder of the secret. Anything else raises InvalidWebhookPayload → HTTP 400.

The decrypted event is a single scan, flat JSON:

    {"Waybill": "1349104478", "Status": "SHIPMENT CREATED BY CUSTOMER",
     "StatusCode": "MCRT", "Location": null, "SenderAddress": ...,
     "ReceiverAddress": ..., "UserId": ..., "ChannelCode": ...}

Note the field-name trap: here `Status` is HUMAN TEXT and `StatusCode` is the
code, while the tracking poll's scan entries carry the code in `Status`. The
state rules (tracking.apply_scan) therefore take the code explicitly; the event
is stored verbatim as `last_scan`, which the storefront/admin render fine (they
pick ScanStatusComment/Location/Status/DateTime and show what exists).

The 2-hourly poll stays on after go-live by design — it is the fallback for
missed webhooks, and the two paths converge because both go through apply_scan.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import logging

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from apps.delivery.models import GigShipment
from apps.delivery.gig.tracking import apply_scan

logger = logging.getLogger(__name__)

_SALT_LEN = 16
_IV_LEN = 16
_PBKDF2_ITERATIONS = 10_000
_KEY_LEN = 32


class InvalidWebhookPayload(Exception):
    """Body that is not base64(salt+iv+AES) decryptable with OUR secret into a
    JSON object — i.e. not a genuine GIG event for this account."""


def decrypt_payload(encrypted: str, secret: str) -> dict:
    """Decrypt one webhook body to the event dict, or raise InvalidWebhookPayload."""
    try:
        raw = base64.b64decode(encrypted.strip(), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise InvalidWebhookPayload(f"not base64: {exc}") from exc

    header = _SALT_LEN + _IV_LEN
    ciphertext = raw[header:]
    if len(ciphertext) == 0 or len(ciphertext) % 16 != 0:
        raise InvalidWebhookPayload("ciphertext missing or not block-aligned")

    key = hashlib.pbkdf2_hmac(
        "sha1", secret.encode(), raw[:_SALT_LEN], _PBKDF2_ITERATIONS, dklen=_KEY_LEN
    )
    decryptor = Cipher(algorithms.AES(key), modes.CBC(raw[_SALT_LEN:header])).decryptor()
    padded = decryptor.update(ciphertext) + decryptor.finalize()

    unpadder = padding.PKCS7(128).unpadder()
    try:
        plaintext = unpadder.update(padded) + unpadder.finalize()
        event = json.loads(plaintext.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        # Wrong secret shows up here: garbage bytes fail padding or JSON.
        raise InvalidWebhookPayload(f"decryption produced no JSON object: {exc}") from exc
    if not isinstance(event, dict):
        raise InvalidWebhookPayload("decrypted JSON is not an object")
    return event


def apply_event(event: dict, now) -> str:
    """Apply one decrypted event through the shared state rules.

    Returns the apply_scan outcome, or "unknown_waybill" — which still ACKs 200:
    every event GIG sends our channel was authenticated by decryption, and
    retrying a waybill we cannot match will never start matching.
    """
    waybill = str(event.get("Waybill", "") or "")
    shipment = (
        GigShipment.objects.select_related("order").filter(waybill=waybill).first()
        if waybill
        else None
    )
    if shipment is None:
        logger.warning("gig webhook: no shipment for waybill %r (code %r)",
                       waybill, event.get("StatusCode"))
        return "unknown_waybill"
    outcome = apply_scan(
        shipment, code=str(event.get("StatusCode", "") or ""), scan=event, now=now
    )
    logger.info("gig webhook %s on %s -> %s", event.get("StatusCode"), waybill, outcome)
    return outcome
