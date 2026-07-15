from decimal import Decimal

import pytest

from apps.catalog.factories import (
    BrandFactory,
    CategoryFactory,
    PriceFactory,
    ProductFactory,
    ProductVariantFactory,
)


@pytest.mark.django_db
def test_factories_build_valid_objects():
    brand = BrandFactory()
    assert brand.slug
    cat = CategoryFactory()
    assert cat.slug

    product = ProductFactory(brand=brand)
    product.categories.add(cat)
    assert product.slug
    assert product.status == "active"           # factory sets active by default

    variant = ProductVariantFactory(product=product)
    assert variant.sku
    assert variant.product == product


@pytest.mark.django_db
def test_price_factory_defaults_to_ngn():
    variant = ProductVariantFactory()
    price = PriceFactory(variant=variant)
    assert price.currency.code == "NGN"
    assert price.amount >= Decimal("0")
