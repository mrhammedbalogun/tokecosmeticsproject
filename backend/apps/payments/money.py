"""Minor-unit arithmetic for gateway amounts.

A gateway that wants minor units (Paystack kobo, Stripe cents) is handed
``to_minor(amount, currency)``; one that wants major units (Flutterwave, PayPal)
uses the Decimal directly. This module centralizes the *math* and, critically,
refuses to silently round money it cannot represent in the currency's minor unit —
silent quantization is how you get off-by-one-kobo reconciliation mysteries.

Reads ``Currency.decimal_places`` (NGN=2, zero-decimal currencies=0) — the same
field pricing uses, so there is one source of truth for a currency's precision.
"""
from __future__ import annotations

from decimal import Decimal


def to_minor(amount: Decimal, currency) -> int:
    """Convert a Decimal major-unit amount to an integer in the currency's minor unit.

    Raises ValueError if `amount` carries more precision than the currency allows
    (e.g. 10.999 in a 2-decimal currency) rather than rounding it away.
    """
    # Coerce via str so a stray float (10.99 -> 10.9900000000000002) or a gateway's
    # string amount ("10.99") becomes an exact Decimal instead of a float artifact.
    amount = Decimal(str(amount))
    exponent = currency.decimal_places
    scaled = amount * (Decimal(10) ** exponent)
    if scaled != scaled.to_integral_value():
        raise ValueError(
            f"{amount} has more precision than {currency.code} allows "
            f"({exponent} decimal places) — refusing to round money."
        )
    return int(scaled)


def from_minor(minor: int, currency) -> Decimal:
    """Convert an integer minor-unit amount back to a Decimal major-unit amount."""
    exponent = currency.decimal_places
    return (Decimal(minor) / (Decimal(10) ** exponent)).quantize(
        Decimal(1).scaleb(-exponent)
    )


def format_money(amount: Decimal, currency) -> str:
    """Render money for humans — emails, invoices, admin. "₦1,234,567.50"

    Lives here, next to the math, so a currency's precision has ONE source of truth.
    A template writing `{{ total|floatformat:2 }}` instead would render a zero-decimal
    currency 100x wrong in the customer's inbox — the same class of trap the gateway
    adapters exist to avoid, and it refuses to round for the same reason to_minor does.
    """
    amount = Decimal(str(amount))
    exponent = currency.decimal_places
    scaled = amount * (Decimal(10) ** exponent)
    if scaled != scaled.to_integral_value():
        raise ValueError(
            f"{amount} has more precision than {currency.code} allows "
            f"({exponent} decimal places) — refusing to round money."
        )
    return f"{currency.symbol}{amount:,.{exponent}f}"


def format_percent(percent: Decimal) -> str:
    """A rate as a customer says it — "5" for 5.00, "12.5" for 12.50, "" for nothing.

    Lives beside `format_money` for the same reason `format_money` lives beside the
    minor-unit math: a template writing `{{ rate }}` renders "5.00%", which reads as a
    spreadsheet cell rather than an offer, and every template that got it wrong would get
    it wrong differently. Trims only the zeros that carry no information, so a genuinely
    fractional rate survives intact.

    Mirrors `ratePercent` in storefront/src/lib/referral-terms.ts, which does the same job
    for the marketing page. The two must agree — a customer reading "5% off" on
    /affiliates and "5.00%" on their invoice is a small thing that reads as carelessness.
    """
    percent = Decimal(str(percent))
    if percent == 0:
        return ""
    return f"{percent.normalize():f}"
