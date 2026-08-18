"""Gateway code → the words a human reads.

ONE SPELLING PER GATEWAY, because the same payment is described in three places — the
customer's checkout, the staff order alert, and the admin's payment panel — and staff
matching a bank statement against an alert should not have to work out that "bank
transfer", "Bank transfer" and "bank_transfer" are the same thing.

DELIBERATELY MIRRORS `storefront/src/lib/payment-labels.ts`. The storefront cannot import
Python and this cannot import TypeScript, so the names are duplicated by necessity; keep
the two in step, and prefer changing both to inventing a third spelling here. Only the
NAME is duplicated — the customer-facing `note` in that file has no meaning for staff.

Stripe is present here and absent there. That is not an oversight to copy: the storefront
never renders a Stripe card because Stripe is embedded in our own UI, but a Payment ROW
can carry `stripe`, and an alert that fell through to the raw code would print
"stripe" where every other method prints a name.
"""
from __future__ import annotations

_LABELS = {
    "bank_transfer": "Bank transfer",
    "paystack": "Card / Paystack",
    "flutterwave": "Card / Flutterwave",
    "stripe": "Card / Stripe",
    "paypal": "PayPal",
}


def gateway_label(code: str) -> str:
    """The display name for `code`, or the code itself for one we do not know.

    `Payment.gateway` is free text, so an unknown value is possible — a hand-written row,
    or a gateway added to the registry before this map. Falling back to the raw code
    prints something ugly but TRUE; falling back to "Unknown" or "" would hide which
    gateway took the money at the moment somebody is trying to find out.
    """
    return _LABELS.get(code, code)
