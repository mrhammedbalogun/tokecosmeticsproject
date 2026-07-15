import pytest

from apps.catalog.factories import ProductVariantFactory
from apps.inventory.csv_io import export_stock_csv, import_stock_csv
from apps.inventory.factories import StockItemFactory, WarehouseFactory
from apps.inventory.models import StockItem, StockMovement


@pytest.mark.django_db
def test_import_sets_quantity_via_ledger_and_reports_errors():
    v = ProductVariantFactory(sku="SER-1")
    w = WarehouseFactory(name="Lagos HQ CSV")
    StockItemFactory(variant=v, warehouse=w, quantity=3)

    rows = [
        {"sku": "SER-1", "warehouse": "Lagos HQ CSV", "quantity": "20", "low_stock_threshold": "5"},
        {"sku": "NOPE", "warehouse": "Lagos HQ CSV", "quantity": "5", "low_stock_threshold": ""},
    ]
    report = import_stock_csv(rows, user=None)
    assert report["updated"] == 1
    assert len(report["errors"]) == 1
    assert report["errors"][0]["row"] == 2

    si = StockItem.objects.get(variant=v, warehouse=w)
    assert si.quantity == 20
    # The change went through the ledger (a movement was written), not a raw save.
    assert StockMovement.objects.filter(stock_item=si, delta_quantity=17).exists()


@pytest.mark.django_db
def test_export_contains_stock_row():
    v = ProductVariantFactory(sku="EXP-1")
    w = WarehouseFactory(name="UK Warehouse CSV")
    StockItemFactory(variant=v, warehouse=w, quantity=8, reserved=2)
    text = export_stock_csv()
    assert "EXP-1" in text
    assert "UK Warehouse CSV" in text
    assert "8" in text
