import pytest
from rest_framework.test import APIClient

from apps.catalog.factories import ProductVariantFactory
from apps.catalog.tests.factories_admin import staff_user
from apps.inventory.factories import StockItemFactory, WarehouseFactory
from apps.inventory.models import StockMovement


@pytest.mark.django_db
def test_stock_list_requires_staff():
    assert APIClient().get("/api/v1/admin/stock/").status_code in (401, 403)


@pytest.mark.django_db
def test_stock_list_and_adjust_and_history():
    v = ProductVariantFactory()
    w = WarehouseFactory()
    si = StockItemFactory(variant=v, warehouse=w, quantity=10)
    c = APIClient()
    c.force_authenticate(user=staff_user())

    # list
    r = c.get("/api/v1/admin/stock/")
    assert r.status_code == 200
    assert r.data["count"] >= 1

    # adjust requires reason + note
    r = c.post(
        f"/api/v1/admin/stock/{si.id}/adjust/",
        {"quantity": 25, "reason": "restock", "note": "delivery #4"},
        format="json",
    )
    assert r.status_code == 200, r.data
    si.refresh_from_db()
    assert si.quantity == 25
    assert StockMovement.objects.filter(stock_item=si, reason="restock").exists()

    # adjust without note -> 400
    r = c.post(
        f"/api/v1/admin/stock/{si.id}/adjust/", {"quantity": 5, "reason": "adjustment"}, format="json"
    )
    assert r.status_code == 400

    # movement history for the variant
    r = c.get(f"/api/v1/admin/stock/movements/?variant={v.id}")
    assert r.status_code == 200
    assert any(m["reason"] == "restock" for m in r.data["results"])
