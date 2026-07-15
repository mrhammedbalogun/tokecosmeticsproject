from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.catalog.factories import (
    BrandFactory,
    CategoryFactory,
    PriceFactory,
    ProductFactory,
    ProductVariantFactory,
)


def _priced_product(amount, **kwargs):
    p = ProductFactory(**kwargs)
    v = ProductVariantFactory(product=p)
    PriceFactory(variant=v, amount=Decimal(amount))
    return p


@pytest.mark.django_db
def test_list_hides_unpriced_products():
    _priced_product("1000")
    ProductFactory()  # no price -> hidden
    r = APIClient().get("/api/v1/products/")
    assert r.status_code == 200
    assert r.data["count"] == 1


@pytest.mark.django_db
def test_list_country_price_and_exclusion():
    _priced_product("1000")   # NGN only
    # In NG: visible with NGN from_price. In GB: no GBP price -> hidden.
    r_ng = APIClient().get("/api/v1/products/", HTTP_X_COUNTRY="NG")
    assert r_ng.data["count"] == 1
    row = r_ng.data["results"][0]
    assert row["from_price"] == "1000.00"
    assert row["currency"] == "NGN"

    r_gb = APIClient().get("/api/v1/products/", HTTP_X_COUNTRY="GB")
    assert r_gb.data["count"] == 0


@pytest.mark.django_db
def test_filter_by_brand_and_price_range():
    b = BrandFactory(slug="toke")
    _priced_product("1000", brand=b)
    _priced_product("5000", brand=b)
    _priced_product("9000")  # different brand (None)

    r = APIClient().get("/api/v1/products/?brand=toke&price_min=2000")
    assert {row["from_price"] for row in r.data["results"]} == {"5000.00"}


@pytest.mark.django_db
def test_ordering_price_asc():
    _priced_product("3000")
    _priced_product("1000")
    _priced_product("2000")
    r = APIClient().get("/api/v1/products/?ordering=price_asc")
    prices = [row["from_price"] for row in r.data["results"]]
    assert prices == ["1000.00", "2000.00", "3000.00"]


@pytest.mark.django_db
def test_filter_by_category():
    cat = CategoryFactory(slug="serums")
    p = _priced_product("1000")
    p.categories.add(cat)
    _priced_product("2000")
    r = APIClient().get("/api/v1/products/?category=serums")
    assert r.data["count"] == 1


@pytest.mark.django_db
def test_detail_shows_variant_prices_per_country():
    p = _priced_product("1000")
    r = APIClient().get(f"/api/v1/products/{p.slug}/", HTTP_X_COUNTRY="NG")
    assert r.status_code == 200
    assert r.data["slug"] == p.slug
    assert len(r.data["variants"]) == 1
    price = r.data["variants"][0]["price"]
    assert price["amount"] == "1000.00"
    assert price["currency"] == "NGN"
    assert price["tax_rate"] == "7.50"


@pytest.mark.django_db
def test_detail_404_when_not_sellable_in_country():
    p = _priced_product("1000")  # NGN only
    r = APIClient().get(f"/api/v1/products/{p.slug}/", HTTP_X_COUNTRY="GB")
    assert r.status_code == 404


@pytest.mark.django_db
def test_detail_in_stock_reflects_inventory():
    from apps.core.models import Country
    from apps.inventory.factories import StockItemFactory, WarehouseFactory

    p = _priced_product("1000")
    v = p.variants.first()
    ng = Country.objects.get(code="NG")
    w = WarehouseFactory()
    w.serves_countries.add(ng)
    StockItemFactory(variant=v, warehouse=w, quantity=0)  # no stock

    r = APIClient().get(f"/api/v1/products/{p.slug}/", HTTP_X_COUNTRY="NG")
    assert r.data["variants"][0]["in_stock"] is False

    si = v.stock_items.first()
    si.quantity = 5
    si.save(update_fields=["quantity"])
    r = APIClient().get(f"/api/v1/products/{p.slug}/", HTTP_X_COUNTRY="NG")
    assert r.data["variants"][0]["in_stock"] is True
