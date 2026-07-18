import pytest
from decimal import Decimal

from apps.catalog.factories import ProductVariantFactory
from apps.core.models import Country, Currency
from apps.delivery.factories import DeliveryOptionFactory, DeliveryOptionRateFactory
from apps.delivery.models import DeliveryOption
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


def _clear_seeded_options():
    """Drop the options seeded by delivery migration 0003 (NG/GB/US/CA/ZZ) so the
    single-unpack assertions below see only the option each test creates — the seeded
    ZZ "International Standard" would otherwise also match a DE/ZZ query and break the
    unpack. Mirrors the helper of the same name in test_matching.py."""
    DeliveryOption.objects.all().delete()


def test_quote_required_option_emits_no_price():
    """price MUST be None, not '0.00'. A zero renders as 'Free' and becomes a promise
    the business cannot keep; None makes any frontend that does arithmetic on it break
    loudly instead of silently lying to the customer."""
    _clear_seeded_options()
    zz = Country.objects.get(code="ZZ")
    opt = DeliveryOption.objects.create(
        name="Adex International delivery", kind="manual", price=Decimal("0.00"),
        currency=zz.currency, min_days=7, max_days=21,
        quote_required=True,
        disclaimer="Shipping quoted after you order — typically $35–70 to Europe.",
    )
    opt.countries.add(zz)

    [result] = options_for_address(FakeAddress("DE"), lines=[], subtotal=Decimal("0"), country=zz)

    assert result["price"] is None
    assert result["quote_required"] is True
    assert result["disclaimer"] == "Shipping quoted after you order — typically $35–70 to Europe."


def test_free_over_never_applies_to_a_quote_required_option():
    """free_over turning an unknown cost into a stated 'Free' is the exact false
    promise this field exists to prevent."""
    _clear_seeded_options()
    zz = Country.objects.get(code="ZZ")
    opt = DeliveryOption.objects.create(
        name="Adex International delivery", kind="manual", price=Decimal("0.00"),
        currency=zz.currency, min_days=7, max_days=21, quote_required=True,
        free_over=Decimal("100.00"), disclaimer="Quoted after you order.",
    )
    opt.countries.add(zz)

    [result] = options_for_address(
        FakeAddress("DE"), lines=[], subtotal=Decimal("500.00"), country=zz
    )

    assert result["price"] is None


def test_normal_option_still_emits_a_price_string():
    """Regression guard: a genuine ₦0 'Free Delivery' must still work exactly as before.
    The owner's stated principle — name + amount, possibly zero — is unchanged."""
    _clear_seeded_options()
    ng = Country.objects.get(code="NG")
    opt = DeliveryOption.objects.create(
        name="Free Delivery", kind="manual", price=Decimal("0.00"),
        currency=ng.currency, min_days=1, max_days=3,
    )
    opt.countries.add(ng)

    [result] = options_for_address(FakeAddress("NG"), lines=[], subtotal=Decimal("0"), country=ng)

    assert result["price"] == "0.00"
    assert result["quote_required"] is False
