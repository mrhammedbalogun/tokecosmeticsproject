import pytest

from apps.catalog.models import Brand, Product, ProductVariant
from apps.core.models import Country


@pytest.mark.django_db
def test_product_defaults_and_variant_relation():
    brand = Brand.objects.create(name="Toke", slug="toke")
    p = Product.objects.create(name="Glow Serum", slug="glow-serum", brand=brand)
    assert p.status == "draft"          # default
    assert p.is_featured is False
    assert p.specs == []                # JSON default list
    assert p.faqs == []
    v = ProductVariant.objects.create(product=p, sku="GLOW-50", name="50ml", is_default=True)
    assert list(p.variants.all()) == [v]
    assert v.option_values == {}        # JSON default dict
    assert str(v) == "Glow Serum — 50ml"


@pytest.mark.django_db
def test_available_countries_empty_means_everywhere():
    p = Product.objects.create(name="X", slug="x")
    assert p.available_countries.count() == 0   # empty = available everywhere (interpreted in Plan-05b)


@pytest.mark.django_db
def test_available_countries_can_be_scoped():
    p = Product.objects.create(name="Y", slug="y")
    ng = Country.objects.get(code="NG")
    p.available_countries.add(ng)
    assert list(p.available_countries.all()) == [ng]


@pytest.mark.django_db
def test_sku_unique():
    p = Product.objects.create(name="Z", slug="z")
    ProductVariant.objects.create(product=p, sku="DUP", name="a")
    with pytest.raises(Exception):
        ProductVariant.objects.create(product=p, sku="DUP", name="b")
