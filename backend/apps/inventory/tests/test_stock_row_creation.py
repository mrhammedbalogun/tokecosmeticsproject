"""Creating a stock row where none exists (Plan-17c Task 4).

The endpoint already existed; nothing in the admin could reach it, which is the gap 17a
Task 7 recorded. These tests pin the two properties the new UI leans on, so a later change
to the serializer cannot quietly break the screen instead of a test.

`quantity` is read-only on create BY DESIGN — `StockItemSerializer` says numbers move only
through `adjust()`, so every change lands in the movement ledger with a reason and a note.
A create that could set a count would be the one stock change with no ledger entry, which
is why the admin creates the row and then adjusts it rather than posting a number here.
"""
import pytest
from rest_framework.test import APIClient

from apps.catalog.factories import ProductVariantFactory
from apps.catalog.tests.factories_admin import staff_user
from apps.inventory.factories import StockItemFactory, WarehouseFactory
from apps.inventory.models import StockItem

pytestmark = pytest.mark.django_db


@pytest.fixture
def client():
    c = APIClient()
    c.force_authenticate(user=staff_user())
    return c


def test_creates_a_row_at_zero(client):
    variant = ProductVariantFactory()
    warehouse = WarehouseFactory()

    response = client.post(
        "/api/v1/admin/stock/",
        {"variant": variant.id, "warehouse": warehouse.id, "low_stock_threshold": 3},
        format="json",
    )

    assert response.status_code == 201, response.data
    item = StockItem.objects.get(variant=variant, warehouse=warehouse)
    assert (item.quantity, item.reserved, item.low_stock_threshold) == (0, 0, 3)


def test_A_COUNT_POSTED_HERE_IS_IGNORED(client):
    """The property the admin's two-step flow depends on. If this ever started working,
    stock could enter the system without a movement row explaining where it came from."""
    variant = ProductVariantFactory()
    warehouse = WarehouseFactory()

    client.post(
        "/api/v1/admin/stock/",
        {"variant": variant.id, "warehouse": warehouse.id, "quantity": 500},
        format="json",
    )

    assert StockItem.objects.get(variant=variant, warehouse=warehouse).quantity == 0


def test_a_second_row_for_the_same_pair_is_refused(client):
    """`unique_together` means the grid can offer "start stocking" on an absent cell
    without racing itself: two operators clicking at once produce one row and one 400."""
    variant = ProductVariantFactory()
    warehouse = WarehouseFactory()
    StockItemFactory(variant=variant, warehouse=warehouse, quantity=4)

    response = client.post(
        "/api/v1/admin/stock/",
        {"variant": variant.id, "warehouse": warehouse.id},
        format="json",
    )

    assert response.status_code == 400
    assert StockItem.objects.filter(variant=variant, warehouse=warehouse).count() == 1
