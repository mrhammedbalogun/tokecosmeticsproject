from decimal import Decimal

import pytest

from apps.catalog.factories import PriceFactory, ProductFactory, ProductVariantFactory
from apps.catalog.models import Product
from apps.catalog.services import annotate_min_price, sellable_in
from apps.core.models import Country


@pytest.mark.django_db
def test_sellable_requires_price():
    ng = Country.objects.get(code="NG")
    p = ProductFactory()
    v = ProductVariantFactory(product=p)
    assert sellable_in(p, ng) is False          # no price yet -> hidden
    PriceFactory(variant=v, amount=Decimal("1000"))
    assert sellable_in(p, ng) is True


@pytest.mark.django_db
def test_sellable_respects_available_countries():
    ng = Country.objects.get(code="NG")
    gb = Country.objects.get(code="GB")
    p = ProductFactory()
    v = ProductVariantFactory(product=p)
    PriceFactory(variant=v, amount=Decimal("1000"))   # NGN price
    p.available_countries.add(ng)                      # restricted to NG
    assert sellable_in(p, ng) is True
    assert sellable_in(p, gb) is False                 # not in available_countries


@pytest.mark.django_db
def test_annotate_min_price_filters_by_currency_context():
    ng = Country.objects.get(code="NG")
    p = ProductFactory()
    v = ProductVariantFactory(product=p)
    PriceFactory(variant=v, amount=Decimal("2500"))
    qs = annotate_min_price(Product.objects.all(), ng)
    got = qs.get(pk=p.pk)
    assert got.min_price == Decimal("2500")
