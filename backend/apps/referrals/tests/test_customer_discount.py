"""The referred CUSTOMER's own discount (2026-08-27) — the buyer's half of the programme.

Two rules are worth more than the rest and each has a test that names it:

* the discount is a REAL price reduction, so it leaves the tax base, and
* the referrer's commission is worked out AFTER it (Hammed's ruling), so the referrer
  earns their percentage of what the customer actually paid.

Everything else here exists to pin the refusals — the discount must be reachable by
exactly the orders a commission is reachable by, and by no others.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from apps.core.models import BusinessDecisions
from apps.referrals.services import (
    accrue_for_order,
    commission_base,
    customer_discount_percent,
)
from apps.referrals.tests.factories import customer, gb, make_order, ng, referrer

pytestmark = pytest.mark.django_db


def _decisions(**kwargs) -> BusinessDecisions:
    row = BusinessDecisions.load()
    for field, value in kwargs.items():
        setattr(row, field, value)
    row.save()
    return row


# ── what the row seeds to ────────────────────────────────────────────────────────────


def test_it_starts_at_the_published_ten_and_five_with_no_migration_step():
    """`load()` seeds from settings on first touch. A deploy that never opens the admin
    page must behave exactly as the published terms say — this is the test that makes
    "no data migration needed" a claim rather than a hope."""
    row = BusinessDecisions.load()
    assert row.referrer_commission_percent == Decimal("10.00")
    assert row.customer_discount_percent == Decimal("5.00")
    assert row.customer_discount_first_order_only is False


# ── who gets it ──────────────────────────────────────────────────────────────────────


def test_an_attributed_order_gets_the_discount(django_user_model):
    buyer = customer(django_user_model, "buyer@x.com")
    _ref, profile = referrer(django_user_model, "ref@x.com")
    assert customer_discount_percent(profile.code, buyer) == Decimal("5.00")


def test_no_attribution_means_no_discount(django_user_model):
    """The function takes the ATTRIBUTED code, so "" is every refusal at once — unknown
    code, blocked referrer, self-referral. That is the whole design: one list of rules
    protects the commission and the discount, and there is no second list to drift."""
    buyer = customer(django_user_model, "buyer@x.com")
    assert customer_discount_percent("", buyer) == Decimal("0.00")


def test_a_self_referral_buys_nobody_five_percent_off(django_user_model):
    """THE ABUSE THIS CLOSES. Without it every customer would apply their own code and
    the shop would be running a permanent 5%-off sale it never advertised.

    Routed through `attribution_code_for_order` exactly as `place_order` routes it, so
    this pins the integration and not just the helper."""
    from apps.referrals.services import attribution_code_for_order

    buyer, profile = referrer(django_user_model, "self@x.com")
    attributed = attribution_code_for_order(profile.code, buyer)

    assert attributed == ""
    assert customer_discount_percent(attributed, buyer) == Decimal("0.00")


def test_zero_percent_switches_that_half_off_without_breaking_attribution(django_user_model):
    """Setting the discount to 0 must leave the REFERRER's side untouched — the order is
    still attributed and still earns commission, it simply costs the customer full price."""
    _decisions(customer_discount_percent=Decimal("0.00"))
    buyer = customer(django_user_model, "buyer@x.com")
    _ref, profile = referrer(django_user_model, "ref@x.com")

    assert customer_discount_percent(profile.code, buyer) == Decimal("0.00")

    order = make_order(user=buyer, referral_code=profile.code)
    assert accrue_for_order(order) is not None


# ── the first-order-only switch ──────────────────────────────────────────────────────


def test_first_order_only_is_off_by_default_so_every_referred_order_gets_it(django_user_model):
    """Hammed's ruling of 2026-08-27: the discount matches the commission's shape — every
    order placed through a link, not just the first."""
    buyer = customer(django_user_model, "buyer@x.com")
    _ref, profile = referrer(django_user_model, "ref@x.com")
    make_order(user=buyer, referral_code=profile.code)

    assert customer_discount_percent(profile.code, buyer) == Decimal("5.00")


def test_first_order_only_refuses_a_customer_who_has_ordered_before(django_user_model):
    _decisions(customer_discount_first_order_only=True)
    buyer = customer(django_user_model, "buyer@x.com")
    _ref, profile = referrer(django_user_model, "ref@x.com")

    assert customer_discount_percent(profile.code, buyer) == Decimal("5.00")
    make_order(user=buyer, referral_code=profile.code)
    assert customer_discount_percent(profile.code, buyer) == Decimal("0.00")


def test_an_abandoned_unpaid_order_does_not_burn_the_first_order_discount(django_user_model):
    """A customer who reached the bank-transfer screen and never paid has not BOUGHT
    anything. Counting that row would deny the welcome discount to exactly the person it
    is meant for, and they would have no way to tell why. Only `REVENUE_STATUSES` count.
    """
    _decisions(customer_discount_first_order_only=True)
    buyer = customer(django_user_model, "buyer@x.com")
    _ref, profile = referrer(django_user_model, "ref@x.com")

    for dead in ("pending_payment", "expired", "cancelled"):
        make_order(user=buyer, status=dead)

    assert customer_discount_percent(profile.code, buyer) == Decimal("5.00")


def test_first_order_means_first_order_ever_not_first_referred_order(django_user_model):
    """The narrower reading — "first order UNDER A REFERRAL" — reopens the same hole by
    another route: order once without a link, then take 5% off for ever afterwards."""
    _decisions(customer_discount_first_order_only=True)
    buyer = customer(django_user_model, "buyer@x.com")
    _ref, profile = referrer(django_user_model, "ref@x.com")

    make_order(user=buyer, referral_code="")  # an ordinary, unattributed order

    assert customer_discount_percent(profile.code, buyer) == Decimal("0.00")


# ── the money rule ───────────────────────────────────────────────────────────────────


def test_the_referred_customers_discount_comes_out_of_the_commission_base(django_user_model):
    """HAMMED'S RULING, 2026-08-27. The referrer earns their percentage of what the
    customer actually paid for the goods, not of the list price nobody paid.

    ₦10,000 of goods, 5% off → the customer pays ₦9,500 and the base is ₦9,500, so 10%
    is ₦950 rather than ₦1,000. The same rule coupons and loyalty points already follow.
    """
    buyer = customer(django_user_model, "buyer@x.com")
    _ref, profile = referrer(django_user_model, "ref@x.com")
    order = make_order(
        user=buyer, subtotal="10000.00", referral_discount="500.00",
        referral_code=profile.code,
    )

    assert commission_base(order) == Decimal("9500.00")

    commission = accrue_for_order(order)
    assert commission.base_amount == Decimal("9500.00")
    assert commission.amount == Decimal("950.00")


def test_a_coupon_and_a_referral_discount_both_come_out_and_do_not_double_count(
    django_user_model,
):
    """They are separate columns and both are real reductions, so the base nets both.
    A base that subtracted only one would overpay the referrer on every order carrying
    both — silently, and in the referrer's favour, which is the direction nobody reports."""
    buyer = customer(django_user_model, "buyer@x.com")
    _ref, profile = referrer(django_user_model, "ref@x.com")
    order = make_order(
        user=buyer, subtotal="10000.00", discount="1000.00", referral_discount="450.00",
        referral_code=profile.code,
    )

    assert commission_base(order) == Decimal("8550.00")


def test_on_a_tax_inclusive_market_the_embedded_tax_still_comes_out_too(django_user_model):
    """The referral discount must not disturb the tax branch. NG prices include VAT, so
    the item tax is subtracted as well — 10,000 goods less 500 discount less 300 tax."""
    buyer = customer(django_user_model, "buyer@x.com")
    _ref, profile = referrer(django_user_model, "ref@x.com")
    order = make_order(
        user=buyer, country=ng(), subtotal="10000.00", referral_discount="500.00",
        tax="300.00", referral_code=profile.code,
    )

    assert order.country.prices_include_tax
    assert commission_base(order) == Decimal("9200.00")


def test_on_a_tax_exclusive_market_the_tax_is_left_alone(django_user_model):
    """GB adds tax on top, so it was never inside the subtotal and must not be subtracted
    — only the discount comes out."""
    buyer = customer(django_user_model, "buyer@x.com")
    _ref, profile = referrer(django_user_model, "ref@x.com")
    # Set explicitly rather than trusted from the seed: which markets are tax-exclusive
    # is an admin setting now (Plan-37), and a test that reads the seed would start
    # asserting the wrong branch the day somebody flips GB in the fixture data.
    market = gb()
    market.prices_include_tax = False
    market.save(update_fields=["prices_include_tax"])
    order = make_order(
        user=buyer, country=market, subtotal="10000.00", referral_discount="500.00",
        tax="2000.00", referral_code=profile.code,
    )

    assert not order.country.prices_include_tax
    assert commission_base(order) == Decimal("9500.00")


def test_an_order_placed_before_the_column_existed_computes_exactly_as_it_always_did(
    django_user_model,
):
    """`referral_discount_total` defaults to 0, so every historical order — including
    every one migrated from WooCommerce — must be untouched by this change."""
    buyer = customer(django_user_model, "buyer@x.com")
    _ref, profile = referrer(django_user_model, "ref@x.com")
    order = make_order(user=buyer, subtotal="10000.00", referral_code=profile.code)

    assert order.referral_discount_total == Decimal("0.00")
    assert commission_base(order) == Decimal("10000.00")


def test_the_rate_in_force_at_accrual_is_snapshotted_not_re_read(django_user_model):
    """An Owner may move the commission rate the day after an order is placed. The row
    keeps the rate it was EARNED under; changing the decision must never re-cut it."""
    buyer = customer(django_user_model, "buyer@x.com")
    _ref, profile = referrer(django_user_model, "ref@x.com")
    order = make_order(user=buyer, subtotal="10000.00", referral_code=profile.code)

    commission = accrue_for_order(order)
    assert commission.rate_percent == Decimal("10.00")

    _decisions(referrer_commission_percent=Decimal("4.00"))
    commission.refresh_from_db()

    assert commission.rate_percent == Decimal("10.00")
    assert commission.amount == Decimal("1000.00")


def test_moving_the_rate_changes_what_the_next_order_earns(django_user_model):
    """The other half of the snapshot rule: a change has to actually take effect."""
    _decisions(referrer_commission_percent=Decimal("8.00"))
    buyer = customer(django_user_model, "buyer@x.com")
    _ref, profile = referrer(django_user_model, "ref@x.com")
    order = make_order(user=buyer, subtotal="10000.00", referral_code=profile.code)

    commission = accrue_for_order(order)
    assert commission.rate_percent == Decimal("8.00")
    assert commission.amount == Decimal("800.00")


# ── the payment path must survive a broken rate read ─────────────────────────────────


def test_a_database_error_reading_the_rate_cannot_cost_a_payment(django_user_model):
    """THE ONE THAT PAYS FOR ITSELF.

    `accrue_for_order` runs inside `_fulfil_locked`, wrapped in the transaction that
    records a payment already charged at the gateway. A DATABASE error is not a Python
    error: it ABORTS that transaction, and the bare `except` in accrual cannot undo it —
    so a read that fails outside a savepoint would roll back `payment.save()` and lose
    real money.

    This is reachable, not theoretical: `infra/deploy/deploy.sh` starts the new containers
    BEFORE it migrates, so on the release that adds `core_businessdecisions` there are
    seconds where that SELECT hits a table that does not exist.

    Simulated by making the rate read raise a DatabaseError, then asserting the caller can
    still write — which is exactly what `payment.save()` needs to be able to do.
    """
    from unittest import mock

    from django.db import DatabaseError, transaction

    from apps.orders.models import OrderEvent

    buyer = customer(django_user_model, "buyer@x.com")
    _ref, profile = referrer(django_user_model, "ref@x.com")
    order = make_order(user=buyer, referral_code=profile.code)

    with transaction.atomic():  # stands in for the payment transaction
        with mock.patch(
            "apps.core.models.BusinessDecisions.load", side_effect=DatabaseError("boom")
        ):
            assert accrue_for_order(order) is None  # swallowed, never raised

        # The transaction is still usable — this is the assertion that matters, because
        # it is `payment.save()` in production.
        OrderEvent.objects.create(order=order, type="status:paid", message="still works")

    assert OrderEvent.objects.filter(order=order, type="status:paid").exists()
