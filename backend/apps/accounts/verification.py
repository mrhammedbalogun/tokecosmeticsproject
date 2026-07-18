"""Signed email-verification token — mirrors apps.orders.tokens (django.core.signing,
HMAC'd with SECRET_KEY, no table). The email is read OUT of the token, never trusted
from the request body, so a token minted for one address cannot verify another."""
from __future__ import annotations

from datetime import timedelta

from django.core import signing

VERIFY_SALT = "accounts.verify_email"
VERIFY_MAX_AGE = timedelta(days=7)


class VerifyTokenError(Exception):
    """The token is expired, tampered with, wrong-scoped, or not one of ours."""


def make_verify_token(email: str) -> str:
    return signing.dumps({"e": email.lower(), "s": "verify"}, salt=VERIFY_SALT)


def read_verify_token(token: str, max_age=VERIFY_MAX_AGE) -> str:
    try:
        payload = signing.loads(token, salt=VERIFY_SALT, max_age=max_age)
    except signing.BadSignature as exc:  # covers SignatureExpired
        raise VerifyTokenError(str(exc)) from exc
    if not isinstance(payload, dict) or payload.get("s") != "verify" or not payload.get("e"):
        raise VerifyTokenError("token is not a verification token")
    return payload["e"]
