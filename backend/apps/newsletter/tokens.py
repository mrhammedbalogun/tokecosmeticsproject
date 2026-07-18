"""Signed unsubscribe token — mirrors apps.orders.tokens. No stored token, HMAC'd with
SECRET_KEY; the email is read out of the token so a link can only unsubscribe itself."""
from __future__ import annotations

from django.core import signing

UNSUB_SALT = "newsletter.unsubscribe"


class UnsubscribeTokenError(Exception):
    pass


def make_unsubscribe_token(email: str) -> str:
    return signing.dumps({"e": email.lower(), "s": "unsub"}, salt=UNSUB_SALT)


def read_unsubscribe_token(token: str) -> str:
    try:
        payload = signing.loads(token, salt=UNSUB_SALT)  # no expiry — links live in inboxes
    except signing.BadSignature as exc:
        raise UnsubscribeTokenError(str(exc)) from exc
    if not isinstance(payload, dict) or payload.get("s") != "unsub" or not payload.get("e"):
        raise UnsubscribeTokenError("token is not an unsubscribe token")
    return payload["e"]
