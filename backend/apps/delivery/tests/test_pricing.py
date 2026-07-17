import pytest
from decimal import Decimal

from apps.catalog.factories import ProductVariantFactory
from apps.core.models import Country, Currency
from apps.delivery.factories import DeliveryOptionFactory, DeliveryOptionRateFactory
from apps.delivery.services import options_for_address

pytestmark = pytest.mark.django_db


class FakeAddress:
    def __init__(self, country_code):
        self.country_code = country_code
        self.state_region = None
        self.area_region = None


def _ng():
    # NGN + NG are seeded by core migration 0003; get_or_create avoids IntegrityError.
    ngn, _ = Currency.objects.get_or_create(code="NGN", defaults={"symbol": "₦"})
    ng, _ = Country.objects.get_or_create(
        code="NG", defaults={"name": "Nigeria", "currency": ngn, "is_default": True}
    )
    return ng


def test_flat_price_when_no_rates():
    ng = _ng()
    opt = DeliveryOptionFactory(currency=ng.currency, price="2500.00")
    opt.countries.add(ng)
    result = options_for_address(FakeAddress("NG"), lines=[], subtotal=Decimal("0"), country=ng)
    assert result[0]["price"] == "2500.00"


def test_weight_tier_selected_by_total_cart_weight():
    ng = _ng()
    opt = DeliveryOptionFactory(currency=ng.currency, price="0.00")
    opt.countries.add(ng)
    DeliveryOptionRateFactory(option=opt, min_weight_g=0, max_weight_g=1000, price="1000.00")
    DeliveryOptionRateFactory(option=opt, min_weight_g=1001, max_weight_g=None, price="2000.00")
    variant = ProductVariantFactory(weight_grams=600)
    lines = [(variant, 2)]  # 1200g → second tier
    result = options_for_address(FakeAddress("NG"), lines=lines, subtotal=Decimal("0"), country=ng)
    assert result[0]["price"] == "2000.00"


def test_free_over_threshold_zeroes_price():
    ng = _ng()
    opt = DeliveryOptionFactory(currency=ng.currency, price="2500.00", free_over="50000.00")
    opt.countries.add(ng)
    result = options_for_address(FakeAddress("NG"), lines=[], subtotal=Decimal("60000.00"), country=ng)
    assert result[0]["price"] == "0.00"
