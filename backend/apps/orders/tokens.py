"""Signed tracking links.

A tracking token lets someone open an order without logging in, from the link in their
confirmation email. It is a BEARER credential: it sits in an inbox forever, gets
forwarded to partners and family, and turns up in server access logs. Everything here
follows from that.

- **Signed, not stored.** `django.core.signing` HMACs the payload with SECRET_KEY, so
  there's no table to keep and nothing to leak. Rotating SECRET_KEY invalidates every
  token; use SECRET_KEY_FALLBACKS if that ever needs to be graceful.
- **The number is read OUT of the token**, never trusted from the URL. That is what stops
  one order's token from opening another's.
- **Salted per scope.** A token minted for one purpose must never open another endpoint,
  so adding a scope later cannot silently widen tokens already in the wild.
- **90 days.** Long enough for slow international delivery plus a return window; short
  enough that a forwarded year-old email stops working.
- The *view* is what redacts the payload — see OrderTrackingSerializer. This module only
  answers "which order, and is this token real?".
"""
from __future__ import annotations

from datetime import timedelta

from django.core import signing

TRACKING_SALT = "orders.track"
TRACKING_MAX_AGE = timedelta(days=90)


class TrackingTokenError(Exception):
    """The token is expired, tampered with, wrong-scoped, or simply not one of ours."""


def make_tracking_token(number: str) -> str:
    return signing.dumps({"o": number, "s": "track"}, salt=TRACKING_SALT)

def read_tracking_token(token: str, max_age=TRACKING_MAX_AGE) -> str:
    """Return the order number a valid token names, or raise TrackingTokenError."""
    try:
        payload = signing.loads(token, salt=TRACKING_SALT, max_age=max_age)
    except signing.BadSignature as exc:  # covers SignatureExpired
        raise TrackingTokenError(str(exc)) from exc
    if not isinstance(payload, dict) or payload.get("s") != "track" or not payload.get("o"):
        raise TrackingTokenError("token is not a tracking token")
    return payload["o"]
