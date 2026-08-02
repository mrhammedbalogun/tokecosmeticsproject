"""Pure transforms for the order migration (Plan-23). No database, no Django models.

Separated from the importer so the decisions that carry money can be tested against the
real distribution measured on the live stores, without a database in the way.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

# ── order numbers ────────────────────────────────────────────────────────────────────────

#: Store → the prefix its order numbers carry.
#:
#: WHY PREFIXES AT ALL: 26 order IDs exist in BOTH the NG-old and intl stores — their ID
#: ranges overlap (18412-28734 vs 19039-21446) where NG-current's does not. `Order.number`
#: is globally unique, so numbering on the bare WooCommerce id would raise IntegrityError
#: partway through the import, or — with a careless get_or_create — silently merge two
#: unrelated customers' orders into one row. Measured, not assumed.
NUMBER_PREFIX = {
    "legacy_ng": "NG",
    "legacy_ng_old": "OLD",
    "legacy_intl": "INT",
}


def order_number(store: str, wp_id: int) -> str:
    """"NG-16521". Fits `Order.number`'s 20 chars with room to spare."""
    try:
        return f"{NUMBER_PREFIX[store]}-{int(wp_id)}"
    except KeyError as exc:
        raise ValueError(f"unknown store {store!r}") from exc


# ── statuses ─────────────────────────────────────────────────────────────────────────────

#: WooCommerce gateway code → this platform's registry code. Recorded as history on an
#: OrderEvent, NOT used to create a Payment row — see ruling 4. Kept because support will
#: be asked "how did they pay?" and the answer should not require reading WooCommerce.
GATEWAY_NAMES = {
    "bacs": "bank_transfer",
    "paystack": "paystack",
    "rave": "flutterwave",
    "stripe": "stripe",
}

#: The single most expensive line in this migration, so it is a named constant rather than
#: a string in a branch.
#:
#: `wc-on-hold` MEANS THE OPPOSITE OF `on_hold`. In this WooCommerce it is what the `bacs`
#: gateway sets when a customer chooses bank transfer and has not paid — measured: ALL
#: 2,277 of them across the three stores have `date_paid_gmt IS NULL`, worth ₦34.2M on
#: NG-current alone. In this platform `on_hold` means money IS in hand: `orders/services.py`
#: parks a PAID order there and calls the balance a live debt, and `on_hold` is inside
#: `analytics.queries.REVENUE_STATUSES`.
#:
#: Mapping the word to the word would have reported ₦34M of never-collected revenue on the
#: dashboard from day one, and filed 2,277 orders as debts owed to customers who never
#: paid. Nothing would have raised.
#:
#: Decided 2026-08-01: they are `expired` — abandoned, which is what they are. The last 30
#: days' worth go into a chase CSV instead of a 2,277-row queue nobody would read.
UNPAID_ON_HOLD_STATUS = "expired"

#: A status we will not import. `trash` is WooCommerce's recycle bin: somebody deliberately
#: deleted these. Resurrecting them on the new platform undoes a human decision.
SKIP = None


def map_status(wc_status: str, *, paid: bool) -> tuple[str | None, str]:
    """(new status, review_reason). `None` means "do not import this order".

    THE PAYMENT DATE WINS OVER THE STATUS NAME. WooCommerce's status is a label a plugin
    or a human can set; `date_paid_gmt` is a fact about money. Where they disagree this
    returns the money-safe answer and a `review_reason`, rather than picking one silently.
    """
    status = (wc_status or "").strip()
    # WooCommerce stores 'wc-completed'; the `trash` post status has no prefix.
    bare = status[3:] if status.startswith("wc-") else status

    if bare == "trash":
        if paid:
            # Deleted in WooCommerce but the money moved. Too important to drop and too
            # odd to import quietly.
            return "cancelled", (
                "Trashed in WooCommerce but carries a payment date — money moved and the "
                "order was then deleted. Verify before closing."
            )
        return SKIP, ""

    if bare == "completed":
        if not paid:
            return "completed", (
                "Marked completed in WooCommerce with no payment date. Imported as "
                "completed on the WooCommerce record; confirm the money was received."
            )
        return "completed", ""

    if bare == "processing":
        return ("processing", "") if paid else (
            "processing",
            "Marked processing in WooCommerce with no payment date. Confirm payment "
            "before fulfilling.",
        )

    if bare == "on-hold":
        if paid:
            # None exist today. If one ever does, it is genuinely this platform's
            # `on_hold` — money in hand, order parked — and must not be silently expired.
            return "on_hold", (
                "On-hold in WooCommerce WITH a payment date. Unlike the other 2,277, this "
                "one holds money."
            )
        return UNPAID_ON_HOLD_STATUS, ""

    if bare == "cancelled":
        if paid:
            return "cancelled", (
                "Cancelled in WooCommerce but carries a payment date — the customer may "
                "be owed a refund. No payment record was migrated, so any refund is manual."
            )
        return "cancelled", ""

    if bare == "refunded":
        return "refunded", ""

    if bare in ("pending", "failed"):
        # Never paid, never going to be. Not `cancelled`: nobody cancelled them.
        return "expired", ""

    # An unrecognised status is imported and flagged rather than dropped. Losing an order
    # because a plugin invented a status is worse than an admin seeing one they must read.
    return "expired", f"Unrecognised WooCommerce status {status!r} — imported as expired."


#: Statuses that `analytics.queries.REVENUE_STATUSES` counts as money. Duplicated here
#: DELIBERATELY as a tripwire, not as a source of truth: `test_orders_migration` asserts
#: the two agree, so if someone adds a status to the analytics set, this migration's
#: guard test fails and the money question gets asked again.
REVENUE_STATUSES_MIRROR = frozenset(
    {"processing", "shipped", "delivered", "completed", "on_hold", "refunded"}
)


# ── money ────────────────────────────────────────────────────────────────────────────────


def money(value, default="0.00") -> Decimal:
    """WooCommerce decimals arrive as strings, Decimals, floats or None.

    ROUNDING IS EXPLICIT, and the house rule is why. `payments/money.py` refuses to round
    money silently — `to_minor` RAISES rather than lose a kobo. This function cannot take
    that line: it runs over 4,096 historical orders, and one odd row must not kill the
    import. So it makes the two implicit choices explicit instead:

    * `ROUND_HALF_UP`, the money convention, rather than inheriting Python's default
      banker's rounding by accident (which is what this did until a test caught it).
    * Nothing is lost silently: the reconciliation report sums the migrated orders and
      compares them against the WooCommerce totals per store, so any drift this introduces
      shows up as a number a human reads, not as a rounding nobody sees.

    In practice WooCommerce stores these as 8-place decimals whose tail is zeros
    (`26100.00000000`), so this quantises rather than rounds for every real row.
    """
    if value is None or value == "":
        value = default
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, ArithmeticError):
        return Decimal(default)


def subtotal_from(totals: dict) -> Decimal:
    """Goods total = grand total − shipping − tax + discount.

    DERIVED, because WooCommerce does not store a subtotal on the order — it stores the
    line items' subtotals, which do not always sum to the same number once a coupon has
    been applied per-line. The other four figures are copied verbatim from the source, so
    this is the only arithmetic in the whole migration, and it is arranged so that
    `subtotal + shipping + tax − discount == grand_total` holds by construction.
    """
    return (
        money(totals.get("total_amount"))
        - money(totals.get("shipping_total_amount"))
        - money(totals.get("tax_amount"))
        + money(totals.get("discount_total_amount"))
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ── addresses ────────────────────────────────────────────────────────────────────────────

_ADDRESS_FIELDS = (
    "first_name", "last_name", "company", "address_1", "address_2",
    "city", "state", "postcode", "country", "phone", "email",
)


def address_snapshot(row: dict | None) -> dict:
    """A JSON snapshot for `Order.shipping_address` / `billing_address`.

    Snapshots, not FKs (`orders/models.py:49-50`), so the NG state codes ("LA", "FC", …)
    and the 99 NULL ones cost nothing here — an unresolvable region does not block the
    order. Empty strings rather than nulls, matching what checkout writes, so the email
    templates that read these do not have to handle two kinds of missing.
    """
    row = row or {}
    return {f: (row.get(f) or "") for f in _ADDRESS_FIELDS}
