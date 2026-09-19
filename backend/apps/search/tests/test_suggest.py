from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.catalog.factories import PriceFactory, ProductFactory, ProductVariantFactory


def _priced(name, amount="1000"):
    p = ProductFactory(name=name)
    PriceFactory(variant=ProductVariantFactory(product=p), amount=Decimal(amount))
    return p


@pytest.mark.django_db
def test_suggest_returns_names_and_slugs():
    _priced("Rose Water Toner")
    _priced("Rose Gold Serum")
    _priced("Charcoal Mask")
    r = APIClient().get("/api/v1/search/suggest/?q=rose")
    assert r.status_code == 200
    names = {s["name"] for s in r.data}
    assert "Rose Water Toner" in names and "Rose Gold Serum" in names
    assert "Charcoal Mask" not in names
    # `type` joined the row when combos became suggestible — it is what tells the
    # storefront to link /product/<slug> rather than /combo/<slug>.
    assert all({"name", "slug", "type"} == set(s) for s in r.data)
    assert all(s["type"] == "product" for s in r.data)


@pytest.mark.django_db
def test_suggest_empty_query_returns_empty():
    r = APIClient().get("/api/v1/search/suggest/?q=")
    assert r.status_code == 200
    assert r.data == []


@pytest.mark.django_db
def test_suggest_caps_at_six():
    for i in range(8):
        _priced(f"Lip Balm {i}")
    r = APIClient().get("/api/v1/search/suggest/?q=lip")
    assert len(r.data) <= 6
