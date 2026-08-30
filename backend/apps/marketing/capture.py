"""Turning the checkout request's marketing blob into an `OrderAttribution` row.

── THE TRUST BOUNDARY, STATED PLAINLY ──────────────────────────────────────────────────

This data arrives in the checkout request body. In normal operation it is assembled by
the storefront's BFF route from cookies it read server-side, but `/api/v1/checkout/` is a
public endpoint and anybody can post to it directly. So everything here is treated as
attacker-supplied.

What that is worth, and what it is not:

  * It decides NOTHING about money, stock, price or delivery. Contrast `referral_code`,
    which decides who gets paid and is therefore read from an httpOnly cookie by the BFF
    and destructured OUT of the request body (see `app/api/checkout/route.ts`). Nothing
    in here justifies that treatment, and giving it that treatment would mean the pixel
    cookies could never be read at all — they are set by vendor JavaScript, not by us.
  * The worst a forged blob achieves is a wrong or missing match on the forger's OWN
    conversion event: they could claim an ad click they did not make, in the shop's own
    ad account, for the order they just paid for.
  * What it must NOT be able to do is put unbounded attacker-chosen strings into the
    database, into a log line, or into a JSON body sent to Meta. That is what the
    allowlist and the length caps below are for, and they are the actual control.

── CONSENT IS NOT TAKEN ON TRUST EITHER, BUT IT IS TAKEN ───────────────────────────────

A caller can claim `consent.marketing = true` when no banner was ever shown. There is no
server-side way to disprove that — consent lives in the visitor's browser. What the row
gives is the auditable record of what was CLAIMED at collection time, which is the
question that actually gets asked afterwards.
"""
from __future__ import annotations

import ipaddress
import logging

logger = logging.getLogger(__name__)

# Exactly the click ids the four adapters read, and nothing else. `ts` is the capture
# time in Unix seconds, used to reconstruct Meta's `_fbc` — see `channels/meta.build_fbc`.
CLICK_ID_KEYS = frozenset({"fbclid", "ttclid", "sccid", "gclid", "wbraid", "gbraid", "ts"})

# The vendors' own first-party cookies, read out of the jar by the BFF. `ga` is GA4's
# `_ga` client id, which is what ties a server-side purchase to the browsing session
# that produced it (see `channels/ga4._client_id` for what its absence costs).
PIXEL_COOKIE_KEYS = frozenset({"fbp", "fbc", "ttp", "scid", "ga"})

# Generous enough for every real value (Meta's `_fbc` is ~90 characters, a gclid ~100)
# and far short of anything that could be used to bloat a row or a log line.
MAX_ID_LENGTH = 512
MAX_UA_LENGTH = 500
MAX_URL_LENGTH = 1000


def _clean_ids(raw, allowed: frozenset[str]) -> dict:
    """Allowlisted keys, string values, capped length. Anything else is dropped without
    comment — a client sending an unknown key is not an error worth failing a checkout
    over, and it must not reach the database either."""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str | int] = {}
    for key, value in raw.items():
        if key not in allowed or value in (None, ""):
            continue
        if key == "ts":
            # The one numeric field. A non-numeric timestamp is dropped rather than
            # coerced: `build_fbc` falls back to "now", which is a known small
            # inaccuracy, while a coerced garbage integer is an unknown large one.
            try:
                out[key] = int(value)
            except (TypeError, ValueError):
                continue
            continue
        text = str(value)[:MAX_ID_LENGTH]
        if text:
            out[key] = text
    return out


def _clean_ip(raw) -> str | None:
    """A well-formed IPv4/IPv6 address, or None.

    Validated rather than trusted because it is written to a `GenericIPAddressField`
    (which would raise at save time, inside the checkout transaction — a 500 at the till
    for a cosmetic field) and because it is forwarded to four third parties.
    """
    if not raw:
        return None
    try:
        return str(ipaddress.ip_address(str(raw).strip()))
    except ValueError:
        return None


def _clean_version(raw) -> int:
    """The consent version the visitor answered. Non-numeric or negative becomes 0,
    which reads as "no recorded version" — the honest answer, and the same one an order
    placed before consent existed carries."""
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 0
    return value if 0 <= value < 2**31 else 0


def record_attribution(order, blob) -> None:
    """Write the order's attribution snapshot. Never raises.

    Called inside `place_order`'s transaction, in the same "born with the order" spirit
    as `ShippingQuote` and `GigShipment`: created later it would have to be created from
    something that no longer exists.

    NEVER RAISES, for the same reason `referrals.services.accrue_for_order` never does.
    This runs inside the locked checkout transaction. An exception here would roll back
    a placed order — losing a sale — to protect a row whose only consumer is an
    advertising dashboard. A missing snapshot costs one unreported conversion; a raised
    exception costs the order.

    ── THE SAVEPOINT IS NOT OPTIONAL ───────────────────────────────────────────────────

    `try/except` ALONE DOES NOT WORK HERE, and this is the trap the docstring above would
    otherwise walk straight into. When a database error is raised inside an atomic block,
    Django marks the whole transaction for rollback; catching the exception does not undo
    that, and the NEXT query — back in `place_order`, creating the Payment row — dies with
    `TransactionManagementError`. The order would be lost by exactly the mechanism this
    function claims to prevent.

    The inner `atomic()` opens a SAVEPOINT, so a failure here rolls back to it and leaves
    the outer transaction usable.
    """
    from django.db import transaction

    from apps.marketing.models import OrderAttribution

    try:
        data = blob if isinstance(blob, dict) else {}
        consent = data.get("consent") if isinstance(data.get("consent"), dict) else {}
        with transaction.atomic():
            OrderAttribution.objects.create(
                order=order,
                consent_marketing=bool(consent.get("marketing")),
                consent_analytics=bool(consent.get("analytics")),
                consent_version=_clean_version(consent.get("version")),
                click_ids=_clean_ids(data.get("click_ids"), CLICK_ID_KEYS),
                pixel_cookies=_clean_ids(data.get("pixel_cookies"), PIXEL_COOKIE_KEYS),
                client_ip=_clean_ip(data.get("client_ip")),
                client_user_agent=str(data.get("client_user_agent") or "")[:MAX_UA_LENGTH],
                event_source_url=str(data.get("event_source_url") or "")[:MAX_URL_LENGTH],
            )
    except Exception:  # noqa: BLE001 — deliberate; see the docstring
        logger.exception("marketing: could not record attribution for order %s", order.pk)
