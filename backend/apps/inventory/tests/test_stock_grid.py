"""The inventory grid's data (Plan-17c Task 3).

Ruling 3: the grid is variant × warehouse, and **a cell with no `StockItem` is the thing
this screen exists to surface** — 122 of the 244 possible cells are empty in production and
every empty one is the UK Warehouse. So the row for a variant carries a cell for every
active warehouse, present or not, and `stock_item_id: null` is the actionable absence.

Paginating this in the browser was not an option: the page is variant-per-row, the stock
endpoint pages StockItem rows, and a variant with NO row anywhere would never appear in
that list at all — which is precisely the variant somebody is looking for.
"""
import pytest
from rest_framework.test import APIClient

from apps.catalog.factories import ProductVariantFactory
from apps.catalog.tests.factories_admin import staff_user
from apps.inventory.factories import StockItemFactory, WarehouseFactory
from apps.inventory.models import Warehouse

pytestmark = pytest.mark.django_db

URL = "/api/v1/admin/stock/grid/"


@pytest.fixture
def client():
    c = APIClient()
    c.force_authenticate(user=staff_user())
    return c


@pytest.fixture(autouse=True)
def _clean_warehouses():
    """Plan-06 seeds two warehouses by data migration; these tests reason about an exact
    set of columns, so they start from a known one."""
    Warehouse.objects.all().delete()


def test_requires_staff():
    assert APIClient().get(URL).status_code in (401, 403)


def test_a_variant_with_no_stock_anywhere_still_appears(client):
    """The row that matters. It cannot be found by listing StockItems, because it has
    none — and it is exactly the variant somebody needs to start stocking."""
    warehouse = WarehouseFactory(name="Lagos HQ")
    variant = ProductVariantFactory()

    rows = client.get(URL).data["results"]

    assert [r["sku"] for r in rows] == [variant.sku]
    (cell,) = rows[0]["cells"]
    assert cell["warehouse_id"] == warehouse.id
    assert cell["stock_item_id"] is None
    assert cell["quantity"] is None


def test_every_active_warehouse_gets_a_cell_even_where_there_is_no_row(client):
    lagos = WarehouseFactory(name="Lagos HQ")
    uk = WarehouseFactory(name="UK Warehouse")
    variant = ProductVariantFactory()
    StockItemFactory(variant=variant, warehouse=lagos, quantity=12)

    (row,) = client.get(URL).data["results"]

    by_warehouse = {c["warehouse_id"]: c for c in row["cells"]}
    assert by_warehouse[lagos.id]["quantity"] == 12
    assert by_warehouse[lagos.id]["stock_item_id"] is not None
    assert by_warehouse[uk.id]["stock_item_id"] is None


def test_an_inactive_warehouse_is_not_a_column(client):
    """`reserve()` skips inactive warehouses, so a column for one would invite counting
    stock into a place nothing can ever be allocated from."""
    WarehouseFactory(name="Lagos HQ")
    WarehouseFactory(name="Mothballed", is_active=False)
    ProductVariantFactory()

    (row,) = client.get(URL).data["results"]

    assert [c["warehouse_name"] for c in row["cells"]] == ["Lagos HQ"]


def test_search_matches_sku_and_product_name(client):
    WarehouseFactory(name="Lagos HQ")
    wanted = ProductVariantFactory(sku="TOKE-SHEA-200")
    ProductVariantFactory(sku="OTHER-1")

    by_sku = client.get(f"{URL}?search=SHEA").data["results"]
    by_product = client.get(f"{URL}?search={wanted.product.name[:6]}").data["results"]

    assert [r["sku"] for r in by_sku] == ["TOKE-SHEA-200"]
    assert wanted.sku in [r["sku"] for r in by_product]


def test_low_stock_filter_keeps_only_rows_at_or_below_a_threshold(client):
    lagos = WarehouseFactory(name="Lagos HQ")
    low = ProductVariantFactory()
    StockItemFactory(variant=low, warehouse=lagos, quantity=2, low_stock_threshold=5)
    plenty = ProductVariantFactory()
    StockItemFactory(variant=plenty, warehouse=lagos, quantity=90, low_stock_threshold=5)

    rows = client.get(f"{URL}?low_stock=1").data["results"]

    assert [r["sku"] for r in rows] == [low.sku]


def test_a_variant_with_no_row_is_NOT_low_stock(client):
    """An absence is not a shortage. It is a different problem with a different fix
    (create the row), and mixing the two makes the low-stock queue unworkable."""
    WarehouseFactory(name="Lagos HQ")
    ProductVariantFactory()

    rows = client.get(f"{URL}?low_stock=1").data["results"]

    assert rows == []


def test_a_row_carries_what_the_screen_prints(client):
    lagos = WarehouseFactory(name="Lagos HQ")
    variant = ProductVariantFactory()
    StockItemFactory(variant=variant, warehouse=lagos, quantity=7, reserved=2)

    (row,) = client.get(URL).data["results"]

    assert row["variant_id"] == variant.id
    assert row["product_name"] == variant.product.name
    assert row["product_slug"] == variant.product.slug
    assert row["variant_name"] == variant.name
    (cell,) = row["cells"]
    assert (cell["quantity"], cell["reserved"], cell["available"]) == (7, 2, 5)


def test_the_columns_are_reported_once_for_the_whole_grid(client):
    """The header has to come from somewhere stable. Deriving it from the rows on screen
    would reshuffle the table as you page through it."""
    lagos = WarehouseFactory(name="Lagos HQ")
    uk = WarehouseFactory(name="UK Warehouse")
    ProductVariantFactory()

    body = client.get(URL).data

    assert [w["id"] for w in body["warehouses"]] == sorted([lagos.id, uk.id])
