import pytest
from datetime import timedelta
from decimal import Decimal
from django.utils import timezone

from apps.checkout.factories import CouponFactory
from apps.checkout.models import CouponRedemption
from apps.checkout.services.coupons import validate_coupon
from apps.core.models import Country, Currency

pytestmark = pytest.mark.django_db


def _ng():
    # NGN/NG are seeded by core migration 0003; reuse (override) rather than re-create.
    ngn, _ = Currency.objects.update_or_create(code="NGN", defaults={"symbol": "₦"})
    country, _ = Country.objects.update_or_create(
        code="NG", defaults={"name": "Nigeria", "currency": ngn, "is_default": True}
    )
    return country


def test_unknown_code_returns_not_found():
    ng = _ng()
    res = validate_coupon("NOPE", subtotal=Decimal("5000"), country=ng)
    assert not res.ok and res.error_code == "not_found"


def test_case_insensitive_lookup():
    ng = _ng()
    CouponFactory(code="SUMMER", type="percent", value="10.00")
    res = validate_coupon("summer", subtotal=Decimal("5000"), country=ng)
    assert res.ok and res.coupon.code == "SUMMER"


def test_expired_and_not_started():
    ng = _ng()
    now = timezone.now()
    CouponFactory(code="OLD", ends_at=now - timedelta(days=1))
    CouponFactory(code="FUTURE", starts_at=now + timedelta(days=1))
    assert validate_coupon("OLD", Decimal("5000"), ng).error_code == "expired"
    assert validate_coupon("FUTURE", Decimal("5000"), ng).error_code == "not_started"


def test_min_subtotal_not_met():
    ng = _ng()
    CouponFactory(code="BIG", min_subtotal="10000.00")
    assert validate_coupon("BIG", Decimal("5000"), ng).error_code == "min_not_met"


def test_fixed_coupon_wrong_currency():
    ng = _ng()
    gbp, _ = Currency.objects.update_or_create(code="GBP", defaults={"symbol": "£"})
    CouponFactory(code="TENOFF", type="fixed", value="10.00", currency=gbp)
    # NG cart is NGN; a GBP fixed coupon can't apply.
    assert validate_coupon("TENOFF", Decimal("5000"), ng).error_code == "wrong_currency"


def test_total_usage_exhausted():
    ng = _ng()
    c = CouponFactory(code="ONEUSE", usage_limit=1)
    CouponRedemption.objects.create(coupon=c, email="a@x.com", order_number="TC-1")
    assert validate_coupon("ONEUSE", Decimal("5000"), ng).error_code == "exhausted"


def test_per_user_usage_exhausted(django_user_model):
    ng = _ng()
    user = django_user_model.objects.create_user(email="u@x.com", password="pw")
    c = CouponFactory(code="ONCEPER", usage_limit_per_user=1)
    CouponRedemption.objects.create(coupon=c, user=user, email=user.email, order_number="TC-2")
    res = validate_coupon("ONCEPER", Decimal("5000"), ng, user=user)
    assert res.error_code == "user_exhausted"


def test_applies_to_gate(django_user_model):
    ng = _ng()
    from apps.catalog.factories import ProductFactory
    p1 = ProductFactory()
    p2 = ProductFactory()
    c = CouponFactory(code="P1ONLY")
    c.applies_to_products.add(p1)
    # cart has only p2 → not valid
    res = validate_coupon("P1ONLY", Decimal("5000"), ng, item_product_ids={p2.id})
    assert res.error_code == "not_valid_for_items"
    # cart includes p1 → valid
    ok = validate_coupon("P1ONLY", Decimal("5000"), ng, item_product_ids={p1.id, p2.id})
    assert ok.ok
