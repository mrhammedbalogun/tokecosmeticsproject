import pytest
from decimal import Decimal

from apps.catalog.factories import ProductVariantFactory
from apps.checkout.factories import CouponFactory
from apps.checkout.services.totals import compute_totals
from apps.core.models import Country, Currency
from apps.pricing.models import Price

pytestmark = pytest.mark.django_db


def _country(include_tax, rate="7.5", code="NG", ccy="NGN"):
    # NGN/USD/... and NG/US/... are seeded by core migration 0003; reuse (override).
    cur, _ = Currency.objects.update_or_create(code=ccy, defaults={"symbol": "¤"})
    country, _ = Country.objects.update_or_create(
        code=code,
        defaults={
            "name": code,
            "currency": cur,
            "is_default": (code == "NG"),
            "tax_rate_percent": Decimal(rate),
            "prices_include_tax": include_tax,
        },
    )
    return country


def _priced_variant(country, amount):
    v = ProductVariantFactory()
    Price.objects.create(variant=v, currency=country.currency, amount=Decimal(amount))
    return v


def test_subtotal_and_inclusive_tax_extraction():
    ng = _country(include_tax=True, rate="7.5")
    v = _priced_variant(ng, "1075.00")
    t = compute_totals([(v, 2)], ng)
    assert t.subtotal == Decimal("2150.00")
    # tax = 2150 - 2150/1.075 = 150.00
    assert t.tax == Decimal("150.00")
    assert t.grand_total == Decimal("2150.00")  # inclusive: tax already inside subtotal
    assert t.currency == "NGN"


def test_exclusive_tax_added_on_top():
    us = _country(include_tax=False, rate="10", code="US", ccy="USD")
    v = _priced_variant(us, "100.00")
    t = compute_totals([(v, 1)], us)
    assert t.subtotal == Decimal("100.00")
    assert t.tax == Decimal("10.00")
    assert t.grand_total == Decimal("110.00")


def test_percent_coupon_discount():
    ng = _country(include_tax=True)
    v = _priced_variant(ng, "1000.00")
    c = CouponFactory(type="percent", value="10.00")
    t = compute_totals([(v, 1)], ng, coupon=c)
    assert t.discount == Decimal("100.00")
    assert t.grand_total == Decimal("900.00")


def test_fixed_coupon_discount_not_below_zero():
    ng = _country(include_tax=True)
    v = _priced_variant(ng, "500.00")
    c = CouponFactory(type="fixed", value="800.00", currency=ng.currency)
    t = compute_totals([(v, 1)], ng, coupon=c)
    assert t.discount == Decimal("500.00")  # capped at subtotal
    assert t.grand_total == Decimal("0.00")


def test_delivery_added_and_free_shipping_coupon_zeroes_it():
    ng = _country(include_tax=True)
    v = _priced_variant(ng, "1000.00")
    t = compute_totals([(v, 1)], ng, delivery_amount=Decimal("1500.00"))
    assert t.delivery == Decimal("1500.00")
    assert t.grand_total == Decimal("2500.00")

    fs = CouponFactory(type="free_shipping", value="0")
    t2 = compute_totals([(v, 1)], ng, delivery_amount=Decimal("1500.00"), coupon=fs)
    assert t2.delivery == Decimal("0.00")
    assert t2.discount == Decimal("0.00")
    assert t2.grand_total == Decimal("1000.00")


def test_per_line_half_up_rounding():
    ng = _country(include_tax=False, rate="0")
    v = _priced_variant(ng, "0.125")  # rounds half-up to 0.13 per unit
    t = compute_totals([(v, 1)], ng)
    assert t.subtotal == Decimal("0.13")


def test_inclusive_tax_half_up_rounding():
    # Forces a non-terminating intermediate inside compute_totals so q2()'s half-up
    # is actually exercised: 100 - 100/1.075 = 6.9767... -> 6.98.
    ng = _country(include_tax=True, rate="7.5")
    v = _priced_variant(ng, "100.00")
    t = compute_totals([(v, 1)], ng)
    assert t.subtotal == Decimal("100.00")
    assert t.tax == Decimal("6.98")
    assert t.grand_total == Decimal("100.00")


def test_unpriced_line_raises():
    ng = _country(include_tax=True)
    v = ProductVariantFactory()  # no price
    with pytest.raises(ValueError):
        compute_totals([(v, 1)], ng)


# ── Tax switches + delivery tax (Plan-37) ──────────────────────────────────────────


def test_master_switch_off_zeroes_tax_but_not_the_price():
    from apps.core.models import StoreSettings

    ng = _country(include_tax=True, rate="7.5")
    v = _priced_variant(ng, "1075.00")
    settings = StoreSettings.load()
    settings.charge_tax = False
    settings.save()
    t = compute_totals([(v, 1)], ng)
    assert t.tax == Decimal("0.00")
    # Inclusive market: the customer pays the admin-entered price either way.
    assert t.grand_total == Decimal("1075.00")


def test_master_switch_off_on_an_exclusive_market_stops_the_surcharge():
    from apps.core.models import StoreSettings

    us = _country(include_tax=False, rate="10", code="US", ccy="USD")
    v = _priced_variant(us, "100.00")
    settings = StoreSettings.load()
    settings.charge_tax = False
    settings.save()
    t = compute_totals([(v, 1)], us)
    assert t.tax == Decimal("0.00")
    assert t.grand_total == Decimal("100.00")  # nothing added on top


def test_country_switch_off_beats_a_nonzero_rate():
    ng = _country(include_tax=True, rate="7.5")
    ng.charge_tax = False
    ng.save()
    v = _priced_variant(ng, "1075.00")
    t = compute_totals([(v, 1)], ng)
    assert t.tax == Decimal("0.00")
    assert t.grand_total == Decimal("1075.00")


def test_delivery_tax_exclusive_market():
    us = _country(include_tax=False, rate="10", code="US", ccy="USD")
    us.tax_applies_to_delivery = True
    us.save()
    v = _priced_variant(us, "100.00")
    t = compute_totals([(v, 1)], us, delivery_amount=Decimal("20.00"))
    # 10% of (100 + 20); the delivery slice reported separately.
    assert t.tax == Decimal("12.00")
    assert t.delivery_tax == Decimal("2.00")
    assert t.grand_total == Decimal("132.00")


def test_delivery_tax_inclusive_market_total_does_not_move():
    gb = _country(include_tax=True, rate="20", code="GB", ccy="GBP")
    gb.tax_applies_to_delivery = True
    gb.save()
    v = _priced_variant(gb, "120.00")
    t = compute_totals([(v, 1)], gb, delivery_amount=Decimal("6.00"))
    # VAT inside 126.00 at 20% = 21.00; inside the 6.00 delivery = 1.00.
    assert t.tax == Decimal("21.00")
    assert t.delivery_tax == Decimal("1.00")
    assert t.grand_total == Decimal("126.00")  # inclusive: nothing added on top


def test_delivery_untaxed_unless_the_market_opts_in():
    us = _country(include_tax=False, rate="10", code="US", ccy="USD")
    v = _priced_variant(us, "100.00")
    t = compute_totals([(v, 1)], us, delivery_amount=Decimal("20.00"))
    assert t.tax == Decimal("10.00")  # items only, as before
    assert t.delivery_tax == Decimal("0.00")
    assert t.grand_total == Decimal("130.00")


# ── the referred customer's discount (2026-08-27) ────────────────────────────────────


def test_the_referral_discount_comes_off_the_goods_and_out_of_the_tax_base():
    """It is a REAL price reduction, not a tender: the customer pays less for the goods,
    so less tax is due on them. A tender (store credit, commission spent at checkout)
    would have to come off AFTER tax instead, or the shop under-declares VAT on goods it
    sold at full price — the asymmetry argued out in Plan-29 Amendment 2(b).

    Exclusive market so the tax line is visible arithmetic rather than an extraction:
    1,000 of goods, 5% off = 950 taxable, 10% tax = 95, total 1,045.
    """
    market = _country(include_tax=False, rate="10", code="GB", ccy="GBP")
    v = _priced_variant(market, "1000.00")
    t = compute_totals([(v, 1)], market, referral_discount_percent=Decimal("5"))

    assert t.subtotal == Decimal("1000.00")
    assert t.referral_discount == Decimal("50.00")
    assert t.referral_discount_percent == Decimal("5")
    assert t.tax == Decimal("95.00")
    assert t.grand_total == Decimal("1045.00")


def test_no_referral_means_the_totals_are_byte_identical_to_before():
    """The default path. Every un-referred order — which is most of them — must compute
    exactly as it did before this feature existed."""
    market = _country(include_tax=False, rate="10", code="GB", ccy="GBP")
    v = _priced_variant(market, "1000.00")

    assert compute_totals([(v, 1)], market) == compute_totals(
        [(v, 1)], market, referral_discount_percent=Decimal("0")
    )


def test_the_referral_discount_is_taken_after_the_coupon_not_beside_it():
    """Charged on what is left after the coupon, so the two can never together exceed the
    goods. 60% off 1,000 leaves 400; 5% of THAT is 20, not 50."""
    market = _country(include_tax=False, rate="0", code="GB", ccy="GBP")
    v = _priced_variant(market, "1000.00")
    coupon = CouponFactory(type="percent", value=Decimal("60"))
    t = compute_totals([(v, 1)], market, coupon=coupon, referral_discount_percent=Decimal("5"))

    assert t.discount == Decimal("600.00")
    assert t.referral_discount == Decimal("20.00")
    assert t.grand_total == Decimal("380.00")


def test_a_hundred_percent_coupon_leaves_the_referral_discount_at_zero_not_negative():
    """The clamp. Nothing left to discount is not an error and must not produce a
    negative line that would add money back onto the order."""
    market = _country(include_tax=False, rate="0", code="GB", ccy="GBP")
    v = _priced_variant(market, "1000.00")
    coupon = CouponFactory(type="percent", value=Decimal("100"))
    t = compute_totals([(v, 1)], market, coupon=coupon, referral_discount_percent=Decimal("5"))

    assert t.referral_discount == Decimal("0.00")
    assert t.grand_total == Decimal("0.00")


def test_the_snapshot_rate_is_zero_when_no_discount_was_actually_given():
    """`referral_discount_percent` rides onto the order so the invoice can say "(5%)".
    When nothing was discounted there is no rate to print, and a stored 5% beside a 0.00
    amount would be a line the customer could not reconcile."""
    market = _country(include_tax=False, rate="0", code="GB", ccy="GBP")
    v = _priced_variant(market, "1000.00")
    coupon = CouponFactory(type="percent", value=Decimal("100"))
    t = compute_totals([(v, 1)], market, coupon=coupon, referral_discount_percent=Decimal("5"))

    assert t.referral_discount_percent == Decimal("0.00")


def test_the_referral_discount_on_a_tax_inclusive_market_takes_exactly_the_headline_percent():
    """NIGERIA — the shop's main market, and the arithmetic most likely to be wrong.

    NG prices INCLUDE VAT, so the displayed ₦10,000 already contains 7.5%. The customer
    must save exactly ₦500 — five percent of the number on the label, not five percent of
    some ex-VAT figure they never saw — and the VAT line must fall with it, because they
    genuinely bought less. Both are asserted here because the inclusive branch derives tax
    by DIVISION (`base - base/(1+r)`), which is where an off-by-a-fraction hides.
    """
    ng = _country(include_tax=True, rate="7.5")
    v = _priced_variant(ng, "10000.00")
    t = compute_totals([(v, 1)], ng, referral_discount_percent=Decimal("5"))

    assert t.subtotal == Decimal("10000.00")
    assert t.referral_discount == Decimal("500.00")
    # The headline promise: 5% off what the customer was quoted.
    assert t.subtotal - t.grand_total == Decimal("500.00")
    assert t.grand_total == Decimal("9500.00")
    # VAT inside the reduced price, not inside the original.
    assert t.tax == Decimal("662.79")


def test_the_inclusive_market_commission_base_matches_that_order():
    """The other half of the same order: what the REFERRER earns on it.

    Pinned beside the totals rather than in the referrals suite so the two halves of one
    transaction are read together — ₦10,000 listed, customer pays ₦9,500, VAT ₦662.79
    comes out, referrer earns 10% of ₦8,837.21. If either side moves, this pair fails.
    """
    from apps.referrals.services import commission_base

    ng = _country(include_tax=True, rate="7.5")
    v = _priced_variant(ng, "10000.00")
    t = compute_totals([(v, 1)], ng, referral_discount_percent=Decimal("5"))

    class _Order:  # only the columns commission_base reads
        subtotal = t.subtotal
        discount_total = t.discount
        referral_discount_total = t.referral_discount
        tax_total = t.tax
        delivery_tax_total = t.delivery_tax
        country = ng

    assert commission_base(_Order()) == Decimal("8837.21")
