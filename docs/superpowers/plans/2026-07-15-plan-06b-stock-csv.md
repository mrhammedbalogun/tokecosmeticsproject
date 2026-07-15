# Plan-06b — Stock CSV Export/Import (mini-plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax. **Depends on Plan-06** (inventory models + `adjust` service must exist).

**Goal:** Let staff bulk-view and bulk-update stock counts via CSV — export current on-hand per (variant × warehouse), and import a CSV that sets on-hand, with a row-level error report.

**Architecture:** Mirrors the Plan-05c catalog CSV pattern (`csv_io.py` pure service + Celery task + two admin endpoints). **Imports go through the locked `inventory.services.adjust()`** — never a raw `StockItem.save()` — so every count change writes a `StockMovement` and the ledger stays the source of truth. Reserved counts are export-only (read-only): CSV changes on-hand `quantity`, never `reserved` (reservations are owned by checkout).

**Tech Stack:** Django, DRF, Celery, Python `csv`. No new dependencies. `IsAdminUser`.

---

## CSV format

Columns: `sku, warehouse, quantity, reserved, available, low_stock_threshold`
- Natural key for import = (`sku`, `warehouse` name). `reserved` and `available` are **export-only** (ignored on import).
- Import sets on-hand `quantity` to the given value via `adjust(reason="adjustment", note="CSV import")`. Unknown sku or warehouse → row error. Missing StockItem for a valid (sku, warehouse) → created at 0 then adjusted.

---

## Task 1: Stock CSV service

**Files:**
- Create: `backend/apps/inventory/csv_io.py`
- Test: `backend/apps/inventory/tests/test_stock_csv.py`

- [ ] **Step 1: Write the failing test**

Create `backend/apps/inventory/tests/test_stock_csv.py`:

```python
import pytest

from apps.catalog.factories import ProductVariantFactory
from apps.inventory.csv_io import export_stock_csv, import_stock_csv
from apps.inventory.factories import StockItemFactory, WarehouseFactory
from apps.inventory.models import StockItem, StockMovement


@pytest.mark.django_db
def test_import_sets_quantity_via_ledger_and_reports_errors():
    v = ProductVariantFactory(sku="SER-1")
    w = WarehouseFactory(name="Lagos HQ")
    StockItemFactory(variant=v, warehouse=w, quantity=3)

    rows = [
        {"sku": "SER-1", "warehouse": "Lagos HQ", "quantity": "20",
         "low_stock_threshold": "5"},
        {"sku": "NOPE", "warehouse": "Lagos HQ", "quantity": "5", "low_stock_threshold": ""},
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
    w = WarehouseFactory(name="UK Warehouse")
    StockItemFactory(variant=v, warehouse=w, quantity=8, reserved=2)
    text = export_stock_csv()
    assert "EXP-1" in text
    assert "UK Warehouse" in text
    assert "8" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest apps/inventory/tests/test_stock_csv.py -v`
Expected: FAIL — `ModuleNotFoundError: apps.inventory.csv_io`.

- [ ] **Step 3: Write the service**

Create `backend/apps/inventory/csv_io.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest apps/inventory/tests/test_stock_csv.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/inventory/csv_io.py apps/inventory/tests/test_stock_csv.py
git commit -m "feat(inventory): stock CSV import/export service (imports via ledgered adjust)"
```

---

## Task 2: Stock CSV endpoints

**Files:**
- Create: `backend/apps/inventory/tasks.py` addition (import task) — or reuse `tasks.py`
- Modify: `backend/apps/inventory/admin_views.py`, `admin_urls.py`
- Test: `backend/apps/inventory/tests/test_stock_csv_api.py`

- [ ] **Step 1: Write the failing test**

Create `backend/apps/inventory/tests/test_stock_csv_api.py`:

```python
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
    w = WarehouseFactory(name="Lagos HQ")
    StockItemFactory(variant=v, warehouse=w, quantity=1)

    c = APIClient()
    c.force_authenticate(user=staff_user())
    csv_text = "sku,warehouse,quantity,reserved,available,low_stock_threshold\nCSV-1,Lagos HQ,40,,,7\n"
    upload = SimpleUploadedFile("stock.csv", csv_text.encode(), content_type="text/csv")
    r = c.post("/api/v1/admin/stock/import.csv", {"file": upload}, format="multipart")
    assert r.status_code == 200, r.data
    assert r.data["updated"] == 1
    StockItem.objects.get(variant=v, warehouse=w).refresh_from_db()
    assert StockItem.objects.get(variant=v, warehouse=w).quantity == 40

    r = c.get("/api/v1/admin/stock/export.csv")
    assert r.status_code == 200
    body = b"".join(r.streaming_content).decode()
    assert "CSV-1" in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest apps/inventory/tests/test_stock_csv_api.py -v`
Expected: FAIL — 404.

- [ ] **Step 3: Add the import task**

Append to `backend/apps/inventory/tasks.py`:

```python
from apps.inventory.csv_io import import_stock_csv, parse_csv_bytes


@shared_task
def import_stock_csv_task(raw_bytes: bytes, user_id=None) -> dict:
    user = None
    if user_id:
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.filter(pk=user_id).first()
    return import_stock_csv(parse_csv_bytes(raw_bytes), user=user)
```

- [ ] **Step 4: Add the views**

Append to `backend/apps/inventory/admin_views.py`:

```python
from django.http import StreamingHttpResponse
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.views import APIView

from apps.inventory.csv_io import export_stock_csv
from apps.inventory.tasks import import_stock_csv_task


class StockCSVExportView(APIView):
    permission_classes = [permissions.IsAdminUser]

    def get(self, request):
        resp = StreamingHttpResponse(iter([export_stock_csv()]), content_type="text/csv")
        resp["Content-Disposition"] = "attachment; filename=stock.csv"
        return resp


class StockCSVImportView(APIView):
    permission_classes = [permissions.IsAdminUser]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        upload = request.data.get("file")
        if upload is None:
            return Response({"detail": "No file provided."}, status=400)
        result = import_stock_csv_task.delay(upload.read(), user_id=request.user.id)
        return Response(result.get(), status=200)  # eager inline (PLAN-05c-async note applies)
```

- [ ] **Step 5: Wire routes**

In `backend/apps/inventory/admin_urls.py`, add the CSV paths BEFORE the router (so `stock/export.csv` isn't captured as a stock pk):

```python
from apps.inventory.admin_views import (
    StockCSVExportView,
    StockCSVImportView,
    StockItemAdminViewSet,
    StockMovementListView,
)

urlpatterns = [
    path("stock/export.csv", StockCSVExportView.as_view(), name="admin-stock-export"),
    path("stock/import.csv", StockCSVImportView.as_view(), name="admin-stock-import"),
    path("stock/movements/", StockMovementListView.as_view(), name="admin-stock-movements"),
] + router.urls
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run python -m pytest apps/inventory/tests/test_stock_csv_api.py -v`
Expected: PASS (2 tests).

- [ ] **Step 7: Commit**

```bash
git add apps/inventory/tasks.py apps/inventory/admin_views.py apps/inventory/admin_urls.py apps/inventory/tests/test_stock_csv_api.py
git commit -m "feat(inventory): admin stock CSV export + import endpoints"
```

---

## Final verification

- [ ] `uv run python -m pytest -q` (Postgres) — all green.
- [ ] Manual: export stock CSV, bump a quantity in the file, re-import, confirm the report + that a `StockMovement` recorded the change (not a silent save).

**CHECKPOINT:** show Hammed a stock CSV round-trip report + the movement row proving the import was ledgered.

## Self-review note

- Imports mutate stock ONLY via `adjust()` (locked + ledgered) — the one correctness rule, tested by asserting a `StockMovement` exists after import. `reserved`/`available` are export-only. No Fable consult needed: this mirrors the established Plan-05c catalog CSV pattern with that single inventory-specific guard.
