from decimal import Decimal

import pytest
from django.utils import timezone

from apps.catalog.models import Product, ProductVariant
from apps.core.models import Country, Currency
from apps.pricing.models import Price
from apps.pricing.services import resolve_price


@pytest.fixture
def variant(db):
    p = Product.objects.create(name="Serum", slug="serum")
    return ProductVariant.objects.create(product=p, sku="S-1", name="50ml", is_default=True)


@pytest.mark.django_db
def test_returns_none_when_no_price(variant):
    ng = Country.objects.get(code="NG")
    assert resolve_price(variant, ng) is None


@pytest.mark.django_db
def test_currency_default_used_when_no_country_row(variant):
    ngn = Currency.objects.get(code="NGN")
    ng = Country.objects.get(code="NG")
    Price.objects.create(variant=variant, currency=ngn, country=None, amount=Decimal("5000.00"))
    rp = resolve_price(variant, ng)
    assert rp is not None
    assert rp.amount == Decimal("5000.00")
    assert rp.currency == "NGN"
    assert rp.tax_rate == Decimal("7.50")          # from NG
    assert rp.prices_include_tax is True


@pytest.mark.django_db
def test_country_override_beats_currency_default(variant):
    ngn = Currency.objects.get(code="NGN")
    ng = Country.objects.get(code="NG")
    Price.objects.create(variant=variant, currency=ngn, country=None, amount=Decimal("5000.00"))
    Price.objects.create(variant=variant, currency=ngn, country=ng, amount=Decimal("4500.00"))
    assert resolve_price(variant, ng).amount == Decimal("4500.00")


@pytest.mark.django_db
def test_expired_sale_window_is_ignored(variant):
    ngn = Currency.objects.get(code="NGN")
    ng = Country.objects.get(code="NG")
    now = timezone.now()
    # An expired windowed price + a plain price -> the plain one wins (expired ignored).
    Price.objects.create(
        variant=variant, currency=ngn, country=ng, amount=Decimal("3000.00"),
        starts_at=now - timezone.timedelta(days=10), ends_at=now - timezone.timedelta(days=5),
    )
    Price.objects.create(variant=variant, currency=ngn, country=ng, amount=Decimal("4500.00"))
    assert resolve_price(variant, ng).amount == Decimal("4500.00")


@pytest.mark.django_db
def test_active_window_price_wins(variant):
    ngn = Currency.objects.get(code="NGN")
    ng = Country.objects.get(code="NG")
    now = timezone.now()
    Price.objects.create(variant=variant, currency=ngn, country=ng, amount=Decimal("4500.00"))
    Price.objects.create(
        variant=variant, currency=ngn, country=ng, amount=Decimal("3999.00"),
        starts_at=now - timezone.timedelta(days=1), ends_at=now + timezone.timedelta(days=1),
    )
    assert resolve_price(variant, ng).amount == Decimal("3999.00")
