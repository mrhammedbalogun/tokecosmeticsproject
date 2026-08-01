"""Pure stock CSV import/export. Imports mutate stock ONLY via services.adjust()
so every change is a locked, ledgered movement."""
from __future__ import annotations

import csv
import io

from django.db import transaction

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


class _DryRunRollback(Exception):
    """Raised to unwind the dry-run's transaction. Never escapes `import_stock_csv`."""


def import_stock_csv(rows, user=None, dry_run: bool = False) -> dict:
    """Apply a stock CSV, or report what applying it WOULD do.

    ── THE DRY-RUN IS THE REAL IMPORT, ROLLED BACK ────────────────────────────────────

    Plan-17c ruling 2 asks for one code path with a flag and forbids a parallel
    implementation, because "a dry-run that can disagree with the real thing is worse than
    none" — the operator trusts the preview and then applies something else. A separate
    `simulate()` would have to re-derive every rule in `_apply_row` (unknown SKU, unknown
    warehouse, non-integer quantity, create-vs-update) and would drift the first time one
    of them changed.

    So the dry-run runs `_apply_row` for real, inside a transaction it then throws away.
    The preview cannot disagree with the apply because it IS the apply. `adjust()` writes
    only to the database — no mail, no Celery, no cache — so rolling it back leaves nothing
    behind. If it ever gains a non-transactional side effect, this stops being safe and
    the note in `services.adjust` should say so.

    Each row additionally gets its OWN savepoint. Under one enclosing transaction a failed
    row would abort every statement after it in Postgres, so the batch would collapse at
    the first bad line instead of collecting per-row errors as it promises. That
    savepoint benefits the real import identically — a row that half-applied and raised
    no longer leaves its fragment behind.
    """
    report = {"created": 0, "updated": 0, "errors": [], "dry_run": dry_run}

    def _run() -> None:
        for i, row in enumerate(rows, start=1):
            try:
                with transaction.atomic():  # savepoint: one bad row must not end the batch
                    outcome = _apply_row(row, user)
            except Exception as exc:  # noqa: BLE001 — collect, don't abort the batch
                report["errors"].append({"row": i, "error": str(exc)})
            else:
                report[outcome] += 1

    if not dry_run:
        _run()
        return report

    try:
        with transaction.atomic():
            _run()
            raise _DryRunRollback
    except _DryRunRollback:
        pass
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
