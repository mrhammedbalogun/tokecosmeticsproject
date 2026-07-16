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
