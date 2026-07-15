import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.catalog.factories import ProductVariantFactory
from apps.catalog.tests.factories_admin import staff_user
from apps.inventory.factories import StockItemFactory, WarehouseFactory
from apps.inventory.models import StockItem


@pytest.mark.django_db
def test_stock_csv_endpoints_require_staff():
    assert APIClient().get("/api/v1/admin/stock/export.csv").status_code in (401, 403)


@pytest.mark.django_db
def test_stock_csv_import_roundtrip(settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    v = ProductVariantFactory(sku="CSV-1")
    w = WarehouseFactory(name="Lagos HQ CSVAPI")
    StockItemFactory(variant=v, warehouse=w, quantity=1)

    c = APIClient()
    c.force_authenticate(user=staff_user())
    csv_text = (
        "sku,warehouse,quantity,reserved,available,low_stock_threshold\n"
        "CSV-1,Lagos HQ CSVAPI,40,,,7\n"
    )
    upload = SimpleUploadedFile("stock.csv", csv_text.encode(), content_type="text/csv")
    r = c.post("/api/v1/admin/stock/import.csv", {"file": upload}, format="multipart")
    assert r.status_code == 200, r.data
    assert r.data["updated"] == 1
    assert StockItem.objects.get(variant=v, warehouse=w).quantity == 40

    r = c.get("/api/v1/admin/stock/export.csv")
    assert r.status_code == 200
    body = b"".join(r.streaming_content).decode()
    assert "CSV-1" in body
