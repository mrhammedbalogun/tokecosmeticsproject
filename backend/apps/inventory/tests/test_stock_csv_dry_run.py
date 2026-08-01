"""The stock CSV dry-run (Plan-17c Task 2).

Ruling 2: one code path with a flag, never a parallel implementation — "a dry-run that can
disagree with the real thing is worse than none". So the dry-run IS the real import, run
inside a transaction that is then rolled back. There is no second row-handling function to
drift out of step, and the report is produced by the same counters.

These tests are written to fail if anyone ever "optimises" that into a separate simulate()
path: they assert the two runs agree on counts AND on per-row errors, for the same file.
"""
import pytest

from apps.catalog.factories import ProductVariantFactory
from apps.inventory.csv_io import import_stock_csv
from apps.inventory.factories import StockItemFactory, WarehouseFactory
from apps.inventory.models import StockItem, StockMovement

pytestmark = pytest.mark.django_db


def _rows(sku, warehouse, qty):
    return [{"sku": sku, "warehouse": warehouse, "quantity": str(qty)}]


def test_dry_run_reports_what_a_real_run_would_do():
    variant = ProductVariantFactory()
    warehouse = WarehouseFactory()

    report = import_stock_csv(_rows(variant.sku, warehouse.name, 42), dry_run=True)

    assert report["created"] == 1
    assert report["errors"] == []
    assert report["dry_run"] is True


def test_DRY_RUN_WRITES_NOTHING():
    """The whole point. A dry-run that left a StockItem behind would be a real import with
    a reassuring name."""
    variant = ProductVariantFactory()
    warehouse = WarehouseFactory()
    movements_before = StockMovement.objects.count()

    import_stock_csv(_rows(variant.sku, warehouse.name, 42), dry_run=True)

    assert not StockItem.objects.filter(variant=variant, warehouse=warehouse).exists()
    assert StockMovement.objects.count() == movements_before


def test_dry_run_does_not_move_an_existing_quantity():
    variant = ProductVariantFactory()
    warehouse = WarehouseFactory()
    item = StockItemFactory(variant=variant, warehouse=warehouse, quantity=10)

    report = import_stock_csv(_rows(variant.sku, warehouse.name, 99), dry_run=True)

    item.refresh_from_db()
    assert report["updated"] == 1
    assert item.quantity == 10  # untouched


def test_the_two_runs_agree():
    """The property ruling 2 actually asks for: same file, same verdict. Run the dry-run
    first, then the real one, and compare everything the operator is shown."""
    variant = ProductVariantFactory()
    warehouse = WarehouseFactory()
    rows = (
        _rows(variant.sku, warehouse.name, 7)
        + [{"sku": "NO-SUCH-SKU", "warehouse": warehouse.name, "quantity": "1"}]
        + [{"sku": variant.sku, "warehouse": "No Such Warehouse", "quantity": "1"}]
        + [{"sku": variant.sku, "warehouse": warehouse.name, "quantity": "not-a-number"}]
    )

    dry = import_stock_csv(list(rows), dry_run=True)
    real = import_stock_csv(list(rows))

    assert (dry["created"], dry["updated"]) == (real["created"], real["updated"])
    assert dry["errors"] == real["errors"]


def test_a_bad_row_does_not_poison_the_rest_of_the_batch():
    """Under one enclosing transaction a failed row would abort every statement after it in
    Postgres, so each row gets its own savepoint. This is why the dry-run can be a rollback
    at all, and it makes the REAL import more robust in exactly the same way."""
    variant = ProductVariantFactory()
    warehouse = WarehouseFactory()
    rows = [
        {"sku": "NO-SUCH-SKU", "warehouse": warehouse.name, "quantity": "1"},
        {"sku": variant.sku, "warehouse": warehouse.name, "quantity": "5"},
    ]

    report = import_stock_csv(rows)

    assert len(report["errors"]) == 1
    assert report["created"] == 1  # the good row after the bad one still landed
    assert StockItem.objects.get(variant=variant, warehouse=warehouse).quantity == 5


def test_a_real_run_still_writes():
    """Guards the flag's default: nobody should be able to make every import a no-op by
    getting the parameter's sense backwards."""
    variant = ProductVariantFactory()
    warehouse = WarehouseFactory()

    report = import_stock_csv(_rows(variant.sku, warehouse.name, 12))

    assert report["dry_run"] is False
    assert StockItem.objects.get(variant=variant, warehouse=warehouse).quantity == 12
