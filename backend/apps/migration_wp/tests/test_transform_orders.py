"""The order-migration transforms, tested against the distribution measured on the live
stores on 2026-08-01. Counts in the comments are real."""

from decimal import Decimal

import pytest

from apps.migration_wp.transform_orders import (
    GATEWAY_NAMES,
    NUMBER_PREFIX,
    REVENUE_STATUSES_MIRROR,
    address_snapshot,
    map_status,
    money,
    order_number,
    subtotal_from,
)

# ── the expensive one ────────────────────────────────────────────────────────────────────


def test_UNPAID_ON_HOLD_NEVER_BECOMES_on_hold():
    """2,277 orders, ₦34.2M on NG-current alone, none of them paid.

    `wc-on-hold` is what the bacs gateway sets when a customer picks bank transfer and
    never sends the money. This platform's `on_hold` means the opposite — money in hand,
    order parked, "the debt is live" — and it sits inside REVENUE_STATUSES. Mapping the
    word to the word puts ₦34M of never-collected revenue on the dashboard.
    """
    status, reason = map_status("wc-on-hold", paid=False)

    assert status == "expired"
    assert status != "on_hold"
    assert status not in REVENUE_STATUSES_MIRROR
    assert reason == ""  # the overwhelmingly normal case must not spam the review queue


def test_NO_UNPAID_ORDER_LANDS_IN_A_REVENUE_STATUS():
    """The general form of the bug above, across every status WooCommerce has here.

    This is the guard: if a future edit routes any unpaid order into a status that
    `analytics.queries` counts as money, the dashboard starts reporting revenue nobody
    received, and nothing else in the suite would notice.
    """
    seen = ["wc-on-hold", "wc-cancelled", "wc-pending", "wc-failed", "trash", "wc-invented"]
    for wc_status in seen:
        status, _ = map_status(wc_status, paid=False)
        assert status not in REVENUE_STATUSES_MIRROR, f"{wc_status} -> {status}"


def test_the_revenue_mirror_still_matches_analytics():
    """The mirror above is a tripwire, not a source of truth. If someone adds a status to
    REVENUE_STATUSES, this fails and the money question gets asked again."""
    from apps.analytics.queries import REVENUE_STATUSES

    assert REVENUE_STATUSES_MIRROR == REVENUE_STATUSES


def test_a_PAID_on_hold_order_is_the_real_on_hold():
    # None exist today. If one appears, it genuinely holds money and must not be expired.
    status, reason = map_status("wc-on-hold", paid=True)
    assert status == "on_hold"
    assert "holds money" in reason


# ── the rest of the status map ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "wc,paid,expected",
    [
        ("wc-completed", True, "completed"),   # 1,164 measured
        ("wc-processing", True, "processing"),  # 21
        ("wc-cancelled", False, "cancelled"),   # 616
        ("wc-refunded", True, "refunded"),      # 1
        ("wc-pending", False, "expired"),       # 1
        ("wc-failed", False, "expired"),        # 3
    ],
)
def test_the_measured_distribution_maps_as_planned(wc, paid, expected):
    assert map_status(wc, paid=paid)[0] == expected


def test_TRASHED_ORDERS_ARE_NOT_RESURRECTED():
    # 6 unpaid trashed orders. Somebody deliberately deleted them; importing them undoes
    # a human decision that this migration has no standing to overrule.
    assert map_status("trash", paid=False)[0] is None


def test_a_trashed_order_that_took_MONEY_is_imported_and_flagged():
    # 1 exists (NG id 11621, ₦22,488.98, paid 2026-04-23). Dropping it would lose a real
    # payment; importing it silently would hide one.
    status, reason = map_status("trash", paid=True)
    assert status == "cancelled"
    assert "money moved" in reason


def test_CANCELLED_BUT_PAID_IS_FLAGGED_because_someone_may_be_owed_a_refund():
    # 3 measured on NG-current, ₦131,692.50 between them.
    status, reason = map_status("wc-cancelled", paid=True)
    assert status == "cancelled"
    assert "refund" in reason.lower()


def test_completed_without_a_payment_date_is_flagged_not_silently_trusted():
    status, reason = map_status("wc-completed", paid=False)
    assert status == "completed"
    assert reason  # a human is told, because this one DOES count as revenue


def test_an_unrecognised_status_is_flagged_not_dropped():
    # Losing an order because a plugin invented a status is worse than an admin reading one.
    status, reason = map_status("wc-some-plugin-status", paid=False)
    assert status == "expired"
    assert "Unrecognised" in reason


@pytest.mark.parametrize("wc", ["wc-completed", "completed"])
def test_the_wc_prefix_is_optional(wc):
    # HPOS rows carry 'wc-completed'; the 13 legacy posts-based intl orders carry the
    # post_status form.
    assert map_status(wc, paid=True)[0] == "completed"


# ── order numbers ────────────────────────────────────────────────────────────────────────


def test_THE_26_COLLIDING_IDS_GET_DIFFERENT_NUMBERS():
    """26 order IDs exist in BOTH the NG-old and intl stores. `Order.number` is unique, so
    without the prefix the import raises partway through — or merges two customers'
    orders."""
    assert order_number("legacy_ng_old", 21000) != order_number("legacy_intl", 21000)
    assert order_number("legacy_ng_old", 21000) == "OLD-21000"
    assert order_number("legacy_intl", 21000) == "INT-21000"


def test_every_number_fits_the_column():
    # Order.number is max_length=20. The largest real id is 28734.
    for store in NUMBER_PREFIX:
        assert len(order_number(store, 99999999)) <= 20


def test_an_unknown_store_raises_rather_than_inventing_a_number():
    with pytest.raises(ValueError, match="unknown store"):
        order_number("legacy_typo", 1)


def test_the_gateway_names_cover_every_measured_method():
    # bacs 2,141 · paystack 1,037 · rave 15 · stripe 21.
    assert set(GATEWAY_NAMES) == {"bacs", "paystack", "rave", "stripe"}
    assert GATEWAY_NAMES["rave"] == "flutterwave"  # Flutterwave's old code


# ── money ────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("34245092.43", "34245092.43"),
        ("26100.00000000", "26100.00"),  # WooCommerce stores 8 places
        (None, "0.00"),
        ("", "0.00"),
        ("not a number", "0.00"),
        (Decimal("12.005"), "12.01"),
    ],
)
def test_money_quantises_and_never_raises(raw, expected):
    # A malformed amount must not kill an import run of 4,096 orders.
    assert money(raw) == Decimal(expected)


def test_THE_SUBTOTAL_IS_DERIVED_SO_THE_TOTALS_ADD_UP():
    """`subtotal + shipping + tax − discount == grand_total`, by construction.

    WooCommerce stores no order subtotal, and summing line items does not reproduce it
    once a coupon has been applied per-line. Deriving it is what keeps the migrated order
    agreeing with the invoice the customer already has.
    """
    totals = {
        "total_amount": "26100.00",
        "shipping_total_amount": "2500.00",
        "tax_amount": "1800.00",
        "discount_total_amount": "500.00",
    }
    subtotal = subtotal_from(totals)

    assert subtotal == Decimal("22300.00")
    assert (
        subtotal
        + money(totals["shipping_total_amount"])
        + money(totals["tax_amount"])
        - money(totals["discount_total_amount"])
    ) == money(totals["total_amount"])


def test_subtotal_of_an_order_with_nothing_but_a_total():
    assert subtotal_from({"total_amount": "100.00"}) == Decimal("100.00")


# ── addresses ────────────────────────────────────────────────────────────────────────────


def test_address_snapshot_fills_every_field_with_a_string():
    # The order emails read these; two kinds of missing (None and "") would mean two code
    # paths in every template.
    snap = address_snapshot({"city": "Lagos", "state": "LA", "country": "NG"})
    assert snap["city"] == "Lagos"
    assert snap["address_2"] == ""
    assert all(isinstance(v, str) for v in snap.values())


def test_address_snapshot_of_nothing_is_still_a_full_shape():
    assert address_snapshot(None)["city"] == ""


def test_the_NG_STATE_CODE_IS_KEPT_VERBATIM():
    # "LA" is 2,195 orders. Region resolution belongs to Address rows, not to the order
    # snapshot, so the code is preserved rather than dropped or guessed at.
    assert address_snapshot({"state": "LA"})["state"] == "LA"


def test_ROUNDING_IS_HALF_UP_NOT_BANKERS():
    # This inherited Python's default (ROUND_HALF_EVEN) until a test caught it. money.py's
    # house rule is that money is never rounded silently, so the choice is made explicitly
    # here rather than by omission.
    assert money("12.005") == Decimal("12.01")
    assert money("12.015") == Decimal("12.02")  # banker's rounding would give 12.02 too
    assert money("12.025") == Decimal("12.03")  # ...but banker's gives 12.02 here


def test_REAL_WOOCOMMERCE_AMOUNTS_ROUND_TRIP_EXACTLY():
    # WooCommerce stores 8 places with a zero tail, so every real row quantises without
    # losing anything. These are actual measured values.
    for raw, expected in [
        ("34245092.43000000", "34245092.43"),
        ("22488.98000000", "22488.98"),
        ("26100.00000000", "26100.00"),
        ("162.50000000", "162.50"),
    ]:
        assert money(raw) == Decimal(expected)
