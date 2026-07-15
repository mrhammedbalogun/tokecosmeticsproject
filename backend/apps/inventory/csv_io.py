"""Pure stock CSV import/export. Imports mutate stock ONLY via services.adjust()
so every change is a locked, ledgered movement."""
from __future__ import annotations

import csv
import io

from apps.catalog.models import ProductVariant
from apps.inventory.models import StockItem, Warehouse
from apps.inventory.services import adjust

COLUMNS = ["sku", "warehouse", "quantity", "reserved", "available", "low_stock_threshold"]


def _apply_row(row: dict, user) -> str:
    sku = (row.get("sku") or "").strip()
    wh_name = (row.get("warehouse") or "").strip()
    if not sku or not wh_name:
        raise ValueError("sku and warehouse are required")
    try:
        qty = int(row["quantity"])
    except (KeyError, ValueError) as exc:
        raise ValueError(f"quantity is not an integer: {row.get('quantity')!r}") from exc
    if qty < 0:
        raise ValueError("quantity cannot be negative")

    try:
        variant = ProductVariant.objects.get(sku=sku)
    except ProductVariant.DoesNotExist as exc:
        raise ValueError(f"unknown sku {sku!r}") from exc
    try:
        warehouse = Warehouse.objects.get(name=wh_name)
    except Warehouse.DoesNotExist as exc:
        raise ValueError(f"unknown warehouse {wh_name!r}") from exc

    item, created = StockItem.objects.get_or_create(variant=variant, warehouse=warehouse)
    threshold = (row.get("low_stock_threshold") or "").strip()
    if threshold:
        item.low_stock_threshold = int(threshold)
        item.save(update_fields=["low_stock_threshold", "updated_at"])
    adjust(item, new_quantity=qty, reason="adjustment", note="CSV import", user=user)
    return "created" if created else "updated"


def import_stock_csv(rows, user=None) -> dict:
    report = {"created": 0, "updated": 0, "errors": []}
    for i, row in enumerate(rows, start=1):
        try:
            report[_apply_row(row, user)] += 1
        except Exception as exc:  # noqa: BLE001 — collect, don't abort the batch
            report["errors"].append({"row": i, "error": str(exc)})
    return report


def parse_csv_bytes(data: bytes) -> list[dict]:
    return list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))


def export_stock_csv() -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=COLUMNS)
    writer.writeheader()
    for si in StockItem.objects.select_related("variant", "warehouse").order_by(
        "warehouse__name", "variant__sku"
    ):
        writer.writerow(
            {
                "sku": si.variant.sku,
                "warehouse": si.warehouse.name,
                "quantity": si.quantity,
                "reserved": si.reserved,
                "available": si.available,
                "low_stock_threshold": si.low_stock_threshold,
            }
        )
    return buf.getvalue()
