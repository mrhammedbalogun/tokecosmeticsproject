from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.catalog.factories import (
    BrandFactory,
    PriceFactory,
    ProductFactory,
    ProductVariantFactory,
)


def _priced(name, amount, **kw):
    p = ProductFactory(name=name, **kw)
    PriceFactory(variant=ProductVariantFactory(product=p), amount=Decimal(amount))
    return p


@pytest.mark.django_db
def test_search_matches_and_is_typo_tolerant():
    _priced("Hydrating Moisturizer", "1000")
    _priced("Matte Lipstick", "2000")
    c = APIClient()
    r = c.get("/api/v1/search/?q=moisturizer")
    assert r.status_code == 200
    assert any(row["name"] == "Hydrating Moisturizer" for row in r.data["results"])
    r = c.get("/api/v1/search/?q=moistriser")  # typo
    assert any(row["name"] == "Hydrating Moisturizer" for row in r.data["results"])


@pytest.mark.django_db
def test_search_card_shape_matches_product_list():
    _priced("Glow Serum", "1500")
    r = APIClient().get("/api/v1/search/?q=glow", HTTP_X_COUNTRY="NG")
    row = r.data["results"][0]
    assert set(row) >= {"name", "slug", "brand", "from_price", "currency", "image"}
    assert row["from_price"] == "1500.00"
    assert row["currency"] == "NGN"


@pytest.mark.django_db
def test_search_filters_by_brand_and_price():
    b = BrandFactory(slug="toke")
    _priced("A Cream", "500", brand=b)
    _priced("B Cream", "5000", brand=b)
    _priced("C Cream", "9000")
    r = APIClient().get("/api/v1/search/?q=cream&brand=toke&price_min=1000")
    assert {row["from_price"] for row in r.data["results"]} == {"5000.00"}


@pytest.mark.django_db
def test_search_hides_unpriced():
    ProductFactory(name="Ghost Product")  # no price
    r = APIClient().get("/api/v1/search/?q=ghost")
    assert r.data["count"] == 0


@pytest.mark.django_db
def test_search_rejects_bad_sort():
    _priced("Thing", "1000")
    r = APIClient().get("/api/v1/search/?q=thing&sort=name;DROP")
    assert r.status_code == 200  # bad sort is ignored, not executed
