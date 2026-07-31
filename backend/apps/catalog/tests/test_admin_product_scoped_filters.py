"""Fetching a whole product's prices and stock in one request — Plan-17a Task 6.

`variant` is an exact-match filter, so the editor's Prices grid and Variants tab would
otherwise issue one request per variant. Production's largest product has TEN variants.
"""
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.catalog.factories import PriceFactory, ProductFactory, ProductVariantFactory
from apps.catalog.tests.factories_admin import staff_user
from apps.inventory.factories import StockItemFactory, WarehouseFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_client():
    c = APIClient()
    c.force_authenticate(user=staff_user())
    return c


def test_prices_filter_by_product(admin_client):
    wanted = ProductFactory(slug="wanted")
    other = ProductFactory(slug="other")
    a = ProductVariantFactory(product=wanted, sku="A")
    b = ProductVariantFactory(product=wanted, sku="B", is_default=False)
    PriceFactory(variant=a, amount=Decimal("1000.00"))
    PriceFactory(variant=b, amount=Decimal("2000.00"))
    PriceFactory(variant=ProductVariantFactory(product=other, sku="C"), amount=Decimal("9.00"))

    r = admin_client.get(f"/api/v1/admin/prices/?variant__product={wanted.id}")

    assert r.status_code == 200, r.data
    assert sorted(row["amount"] for row in r.data["results"]) == ["1000.00", "2000.00"]


def test_stock_filter_by_product(admin_client):
    wanted = ProductFactory(slug="wanted")
    other = ProductFactory(slug="other")
    warehouse = WarehouseFactory(name="Lagos HQ")
    StockItemFactory(
        variant=ProductVariantFactory(product=wanted, sku="A"), warehouse=warehouse, quantity=7
    )
    StockItemFactory(
        variant=ProductVariantFactory(product=other, sku="B"), warehouse=warehouse, quantity=3
    )

    r = admin_client.get(f"/api/v1/admin/stock/?variant__product={wanted.id}")

    assert r.status_code == 200, r.data
    assert [row["quantity"] for row in r.data["results"]] == [7]


def test_stock_rows_name_their_warehouse(admin_client):
    """The Variants tab shows stock PER WAREHOUSE, and there is no warehouse endpoint until
    17c — `warehouse_name` on the serializer is the whole source of that label."""
    product = ProductFactory(slug="p")
    StockItemFactory(
        variant=ProductVariantFactory(product=product, sku="A"),
        warehouse=WarehouseFactory(name="Lagos HQ"),
        quantity=4,
    )

    r = admin_client.get(f"/api/v1/admin/stock/?variant__product={product.id}")

    assert r.data["results"][0]["warehouse_name"] == "Lagos HQ"


def test_one_request_covers_a_ten_variant_product(admin_client, django_assert_max_num_queries):
    """Production's largest product has ten variants. The point of the filter is that this
    is ONE request whose cost does not scale with variant count."""
    product = ProductFactory(slug="big")
    for i in range(10):
        variant = ProductVariantFactory(product=product, sku=f"V-{i}", is_default=i == 0)
        PriceFactory(variant=variant, amount=Decimal("100.00"))

    with django_assert_max_num_queries(8):
        r = admin_client.get(f"/api/v1/admin/prices/?variant__product={product.id}")

    assert r.status_code == 200
    assert r.data["count"] == 10
