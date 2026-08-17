"""Signed confirmation links for external notification recipients.

Mirrors `apps/orders/tokens.py` deliberately — same library, same shape, same reasoning —
so there is one way to do this in the codebase rather than two.

THIS IS NOW THE THIRD COPY of that ~40-line pattern (`orders/tokens.py`,
`newsletter/tokens.py`, this). Three is the point at which a shared
`apps/core/signing.py` taking a salt and a payload schema becomes the boring right answer;
it was not extracted here only because doing so touches two shipped, tested token flows
and this change is already large. Whoever writes the fourth should extract it instead.

WHAT THIS TOKEN IS FOR. An external recipient (`NotificationRecipient` with no `user`) is
an address somebody typed into an admin form. Nothing yet proves a human at that address
agreed to receive a shop's order data, and nothing proves the address was even typed
correctly: `orders@gmali.com` accepts the subscription and then fails silently forever,
because the symptom of a wrong address is identical to the symptom of a working one.
Clicking this link is that proof.

- **Signed, not stored.** No table, nothing to leak, and a token cannot be "used up" out
  of band. Rotating SECRET_KEY invalidates every outstanding link, which is acceptable:
  the recovery path is one button on the admin screen.
- **The row id AND the address are read OUT of the token.** Not because Postgres reuses
  primary keys — bigserial never does — but because the address is what the recipient
  actually consented to. Binding it lets the confirm view check that the row still says
  the same thing it said when the link was minted, and refuse if the Owner has since
  edited it to point somewhere else.
- **Salted per scope**, so a confirmation token can never open the tracking endpoint or
  anything added later.
- **7 days.** Long enough to survive a weekend and a spam folder; short enough that a
  forwarded link from months ago cannot quietly enrol an address nobody remembers.
"""
from __future__ import annotations

from datetime import timedelta

from django.core import signing

CONFIRM_SALT = "notifications.recipient.confirm"
CONFIRM_MAX_AGE = timedelta(days=7)


class ConfirmTokenError(Exception):
    """Expired, tampered with, wrong-scoped, or simply not one of ours."""


def make_confirm_token(recipient_id: int, email: str) -> str:
    return signing.dumps(
        {"r": recipient_id, "e": (email or "").strip().lower(), "s": "confirm"},
        salt=CONFIRM_SALT,
    )


def read_confirm_token(token: str, max_age=CONFIRM_MAX_AGE) -> tuple[int, str]:
    """Return `(recipient_id, email)` a valid token names, or raise ConfirmTokenError."""
    try:
        payload = signing.loads(token, salt=CONFIRM_SALT, max_age=max_age)
    except signing.BadSignature as exc:  # covers SignatureExpired
        raise ConfirmTokenError(str(exc)) from exc
    if (
        not isinstance(payload, dict)
        or payload.get("s") != "confirm"
        or not payload.get("r")
        or not payload.get("e")
    ):
        raise ConfirmTokenError("token is not a recipient confirmation token")
    return int(payload["r"]), str(payload["e"])
