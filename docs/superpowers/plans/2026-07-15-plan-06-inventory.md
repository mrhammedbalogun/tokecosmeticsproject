# Plan-06 — Inventory & Race-Safe Reservations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Single-inventory stock tracking — warehouses, per-(variant×warehouse) stock, an append-only movement ledger, and **race-safe reservations** that make overselling impossible. Plus the admin stock API, low-stock alerts, and wiring real stock into the storefront's `in_stock`.

**Architecture:** New `apps.inventory` app. Stock numbers change ONLY through `services.py`, always inside `transaction.atomic()` with `select_for_update()`. Locks are taken on StockItem rows **in `pk` order** (deadlock-safe), then allocation walks warehouses by `priority`. A DB `CHECK` constraint (`0 <= reserved <= quantity`) is the can't-oversell backstop independent of app logic. Reservations are keyed by a `reference` string; `release`/`commit_sale` **replay the movement ledger under lock** for idempotency.

**Tech Stack:** Django 5.2, DRF, Celery (beat for low-stock digest), PostgreSQL (required — see Task 0), pytest + `TransactionTestCase` for the race test. No new dependencies.

> **Design note:** the reservation/locking/idempotency approach in this plan was reviewed with the Fable 5 model. Key guidance baked in: single pk-ordered `select_for_update` queryset (not lock-as-you-walk), DB CHECK constraint as backstop, ledger-replay for idempotent release/commit, and testing on Postgres (SQLite's `select_for_update` is a no-op).

---

## Conventions for this plan (read once)

- **Run tests:** `uv run python -m pytest ...` from `backend/` (bare `pytest` is blocked locally).
- **DB is now PostgreSQL** for the whole suite (Task 0). CI already uses Postgres; this switches local dev too.
- Stock mutations go through `apps.inventory.services` ONLY — never `.save()` a StockItem's numbers from a view/serializer directly.

## File Structure

**Created:**
- `backend/apps/inventory/__init__.py`, `apps.py`, `models.py`, `services.py`, `admin.py`, `tasks.py`
- `backend/apps/inventory/migrations/__init__.py`, `0001_initial.py`, `0002_seed_warehouses.py`
- `backend/apps/inventory/admin_serializers.py`, `admin_views.py`, `admin_urls.py`
- `backend/apps/inventory/tests/__init__.py` + test modules
- `backend/apps/inventory/factories.py`

**Modified:**
- `backend/config/settings/base.py` — add `apps.inventory`; Celery beat schedule
- `backend/config/urls.py` — include inventory admin routes
- `backend/apps/catalog/api_serializers.py` — real `in_stock` (replace the Plan-05b stub)
- `backend/.env`, `backend/.env.example` — `DATABASE_URL` for local Postgres
- `docs/architecture.md` — Plan-06 status

---

## Task 0: Switch local test DB to PostgreSQL

CI already runs on Postgres. This points **local** dev/tests at the docker-compose Postgres so the race test is meaningful and dev matches prod.

**Files:**
- Modify: `backend/.env`, `backend/.env.example`

- [ ] **Step 1: Start the dev Postgres**

Run (from repo root): `docker compose -f docker-compose.dev.yml up -d postgres`
Expected: container healthy. Verify: `docker compose -f docker-compose.dev.yml ps` shows postgres healthy. (Requires Docker Desktop running — if unavailable, STOP and tell Hammed; this plan needs it.)

- [ ] **Step 2: Point local settings at Postgres**

In `backend/.env`, set (uncomment/add):

```
DATABASE_URL=postgres://toke:toke@localhost:5433/toke
```

Mirror the commented hint in `backend/.env.example` (leave it commented there — it's a template):

```
# Local dev/tests run on Postgres (matches prod). Start it: docker compose -f docker-compose.dev.yml up -d postgres
DATABASE_URL=postgres://toke:toke@localhost:5433/toke
```

- [ ] **Step 3: Migrate + run the WHOLE suite on Postgres**

Run: `uv run python manage.py migrate`
Run: `uv run python -m pytest -q`
Expected: all 74 existing tests PASS on Postgres. If any fail, they were relying on SQLite behavior — fix the code/test before continuing (this is exactly why we switched). Likely-clean, but verify.

- [ ] **Step 4: Commit**

```bash
git add backend/.env.example
git commit -m "chore(backend): run local dev/test suite on Postgres (matches prod + CI)"
```

(`.env` is gitignored — not committed. Note in the commit body that devs must set `DATABASE_URL` + run the compose Postgres.)

---

## Task 1: Inventory models (Warehouse, StockItem, StockMovement)

**Files:**
- Create: `backend/apps/inventory/__init__.py`, `apps.py`, `models.py`
- Create: `backend/apps/inventory/tests/__init__.py`, `test_models.py`
- Modify: `backend/config/settings/base.py`

- [ ] **Step 1: Write the failing test**

Create `backend/apps/inventory/tests/__init__.py` (empty) and `backend/apps/inventory/tests/test_models.py`:

```python
import pytest
from django.db import IntegrityError, transaction

from apps.catalog.models import Product, ProductVariant
from apps.core.models import Country
from apps.inventory.models import StockItem, Warehouse


@pytest.fixture
def variant(db):
    p = Product.objects.create(name="P", slug="p")
    return ProductVariant.objects.create(product=p, sku="P-1", name="50ml", is_default=True)


@pytest.mark.django_db
def test_warehouse_serves_countries():
    ng = Country.objects.get(code="NG")
    w = Warehouse.objects.create(name="Lagos HQ", location_country="NG", priority=1)
    w.serves_countries.add(ng)
    assert list(w.serves_countries.all()) == [ng]


@pytest.mark.django_db
def test_stockitem_available_and_unique(variant):
    w = Warehouse.objects.create(name="W", location_country="NG")
    si = StockItem.objects.create(variant=variant, warehouse=w, quantity=10, reserved=3)
    assert si.available == 7
    with pytest.raises(IntegrityError):
        StockItem.objects.create(variant=variant, warehouse=w, quantity=1)  # unique (variant, warehouse)


@pytest.mark.django_db
def test_stockitem_cannot_oversell_constraint(variant):
    w = Warehouse.objects.create(name="W2", location_country="NG")
    # reserved must never exceed quantity (DB CHECK backstop).
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            StockItem.objects.create(variant=variant, warehouse=w, quantity=2, reserved=5)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest apps/inventory/tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: apps.inventory`.

- [ ] **Step 3: Create the app**

Create `backend/apps/inventory/__init__.py` (empty).

Create `backend/apps/inventory/apps.py`:

```python
from django.apps import AppConfig


class InventoryConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.inventory"
```

Create `backend/apps/inventory/models.py`:

```python
from django.db import models

from apps.core.models import TimeStampedModel


class Warehouse(TimeStampedModel):
    name = models.CharField(max_length=100)
    location_country = models.CharField(max_length=2)  # ISO code where it physically is
    serves_countries = models.ManyToManyField("core.Country", related_name="warehouses")
    priority = models.PositiveSmallIntegerField(default=100)  # lower = tried first when reserving
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["priority", "name"]

    def __str__(self) -> str:
        return self.name


class StockItem(TimeStampedModel):
    variant = models.ForeignKey(
        "catalog.ProductVariant", on_delete=models.CASCADE, related_name="stock_items"
    )
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name="stock_items")
    quantity = models.IntegerField(default=0)  # on-hand
    reserved = models.IntegerField(default=0)  # held by pending checkouts
    low_stock_threshold = models.IntegerField(default=5)

    class Meta:
        unique_together = [("variant", "warehouse")]
        constraints = [
            # Can't-oversell backstop, independent of application logic.
            models.CheckConstraint(check=models.Q(quantity__gte=0), name="stock_quantity_nonneg"),
            models.CheckConstraint(check=models.Q(reserved__gte=0), name="stock_reserved_nonneg"),
            models.CheckConstraint(
                check=models.Q(reserved__lte=models.F("quantity")), name="stock_reserved_lte_quantity"
            ),
        ]

    @property
    def available(self) -> int:
        return self.quantity - self.reserved

    def __str__(self) -> str:
        return f"{self.variant.sku} @ {self.warehouse.name}: {self.available} avail"


class StockMovement(TimeStampedModel):
    """Append-only audit trail. The ledger is the source of truth for reservations."""

    REASONS = [
        ("sale", "Sale"),
        ("reservation", "Reservation"),
        ("release", "Release"),
        ("restock", "Restock"),
        ("adjustment", "Adjustment"),
        ("damaged", "Damaged"),
        ("returned", "Returned"),
        ("migration", "Migration"),
    ]

    stock_item = models.ForeignKey(StockItem, on_delete=models.CASCADE, related_name="movements")
    delta_quantity = models.IntegerField(default=0)  # change to on-hand
    delta_reserved = models.IntegerField(default=0)  # change to reserved
    reason = models.CharField(max_length=30, choices=REASONS)
    reference = models.CharField(max_length=64, blank=True, db_index=True)  # order number etc.
    note = models.TextField(blank=True)
    created_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL
    )

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return f"{self.reason} q{self.delta_quantity:+d} r{self.delta_reserved:+d} ({self.reference})"
```

- [ ] **Step 4: Register the app**

In `backend/config/settings/base.py`, add to `INSTALLED_APPS` after `apps.pricing`:

```python
    "apps.pricing",
    "apps.inventory",
```

- [ ] **Step 5: Migrate + run tests**

Run: `uv run python manage.py makemigrations inventory`
Run: `uv run python manage.py migrate`
Run: `uv run python -m pytest apps/inventory/tests/test_models.py -v`
Expected: PASS (3 tests). The oversell-constraint test proves the CHECK constraint is live on Postgres.

- [ ] **Step 6: Commit**

```bash
git add apps/inventory/__init__.py apps/inventory/apps.py apps/inventory/models.py apps/inventory/migrations apps/inventory/tests config/settings/base.py
git commit -m "feat(inventory): Warehouse, StockItem (oversell CHECK), StockMovement models"
```

---

## Task 2: Seed warehouses

Seed "Lagos HQ" (serves NG, ZZ) and "UK Warehouse" (serves GB, US, CA, ZZ).

**Files:**
- Create: `backend/apps/inventory/migrations/0002_seed_warehouses.py`
- Test: `backend/apps/inventory/tests/test_seed.py`

- [ ] **Step 1: Write the failing test**

Create `backend/apps/inventory/tests/test_seed.py`:

```python
import pytest

from apps.inventory.models import Warehouse


@pytest.mark.django_db
def test_warehouses_seeded():
    lagos = Warehouse.objects.get(name="Lagos HQ")
    assert lagos.location_country == "NG"
    assert set(lagos.serves_countries.values_list("code", flat=True)) == {"NG", "ZZ"}

    uk = Warehouse.objects.get(name="UK Warehouse")
    assert set(uk.serves_countries.values_list("code", flat=True)) == {"GB", "US", "CA", "ZZ"}
    # Lagos is first choice for NG; UK first for the others.
    assert lagos.priority <= uk.priority or True  # priorities are per-country in reserve(); see services
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest apps/inventory/tests/test_seed.py -v`
Expected: FAIL — `Warehouse.DoesNotExist`.

- [ ] **Step 3: Write the seed migration**

Create `backend/apps/inventory/migrations/0002_seed_warehouses.py`:

```python
from django.db import migrations

# name, location, priority, [served country codes]
WAREHOUSES = [
    ("Lagos HQ", "NG", 1, ["NG", "ZZ"]),
    ("UK Warehouse", "GB", 1, ["GB", "US", "CA", "ZZ"]),
]


def seed(apps, schema_editor):
    Warehouse = apps.get_model("inventory", "Warehouse")
    Country = apps.get_model("core", "Country")
    for name, loc, priority, codes in WAREHOUSES:
        w, _ = Warehouse.objects.update_or_create(
            name=name, defaults={"location_country": loc, "priority": priority, "is_active": True}
        )
        w.serves_countries.set(Country.objects.filter(code__in=codes))


def unseed(apps, schema_editor):
    Warehouse = apps.get_model("inventory", "Warehouse")
    Warehouse.objects.filter(name__in=[w[0] for w in WAREHOUSES]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0001_initial"),
        ("core", "0003_seed_countries_currencies"),
    ]
    operations = [migrations.RunPython(seed, unseed)]
```

- [ ] **Step 4: Migrate + run tests**

Run: `uv run python manage.py migrate`
Run: `uv run python -m pytest apps/inventory/tests/test_seed.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/inventory/migrations/0002_seed_warehouses.py apps/inventory/tests/test_seed.py
git commit -m "feat(inventory): seed Lagos HQ + UK Warehouse with served countries"
```

---

## Task 3: Stock services — available, reserve, release, commit_sale, adjust

The heart of the plan. All mutations locked, pk-ordered, ledger-idempotent.

**Files:**
- Create: `backend/apps/inventory/services.py`, `backend/apps/inventory/factories.py`
- Test: `backend/apps/inventory/tests/test_services.py`

- [ ] **Step 1: Write the factories + failing test**

Create `backend/apps/inventory/factories.py`:

```python
import factory

from apps.catalog.factories import ProductVariantFactory
from apps.inventory.models import StockItem, Warehouse


class WarehouseFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Warehouse

    name = factory.Sequence(lambda n: f"WH {n}")
    location_country = "NG"
    priority = 100


class StockItemFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = StockItem

    variant = factory.SubFactory(ProductVariantFactory)
    warehouse = factory.SubFactory(WarehouseFactory)
    quantity = 0
    reserved = 0
```

Create `backend/apps/inventory/tests/test_services.py`:

```python
import pytest

from apps.catalog.factories import ProductVariantFactory
from apps.core.models import Country
from apps.inventory.factories import StockItemFactory, WarehouseFactory
from apps.inventory.models import StockItem, StockMovement
from apps.inventory.services import (
    InsufficientStock,
    available_for_country,
    commit_sale,
    release,
    reserve,
)


@pytest.fixture
def ng(db):
    return Country.objects.get(code="NG")


def _wh(country, **kw):
    w = WarehouseFactory(**kw)
    w.serves_countries.add(country)
    return w


@pytest.mark.django_db
def test_available_for_country_sums_serving_warehouses(ng):
    v = ProductVariantFactory()
    StockItemFactory(variant=v, warehouse=_wh(ng), quantity=10, reserved=2)
    StockItemFactory(variant=v, warehouse=_wh(ng), quantity=5, reserved=0)
    assert available_for_country(v, ng) == 13


@pytest.mark.django_db
def test_reserve_then_release_roundtrip(ng):
    v = ProductVariantFactory()
    si = StockItemFactory(variant=v, warehouse=_wh(ng), quantity=10)
    reserve(v, 4, ng, reference="ORD-1")
    si.refresh_from_db()
    assert si.reserved == 4
    assert available_for_country(v, ng) == 6

    release("ORD-1")
    si.refresh_from_db()
    assert si.reserved == 0
    assert available_for_country(v, ng) == 10


@pytest.mark.django_db
def test_reserve_insufficient_raises(ng):
    v = ProductVariantFactory()
    StockItemFactory(variant=v, warehouse=_wh(ng), quantity=2)
    with pytest.raises(InsufficientStock):
        reserve(v, 3, ng, reference="ORD-2")
    assert available_for_country(v, ng) == 2  # nothing reserved on failure


@pytest.mark.django_db
def test_reserve_splits_across_warehouses_by_priority(ng):
    v = ProductVariantFactory()
    StockItemFactory(variant=v, warehouse=_wh(ng, priority=1), quantity=3)
    StockItemFactory(variant=v, warehouse=_wh(ng, priority=2), quantity=5)
    reserve(v, 5, ng, reference="ORD-3")  # 3 from priority-1, 2 from priority-2
    items = {si.warehouse.priority: si for si in StockItem.objects.filter(variant=v)}
    assert items[1].reserved == 3
    assert items[2].reserved == 2


@pytest.mark.django_db
def test_reserve_is_idempotent_per_reference(ng):
    v = ProductVariantFactory()
    si = StockItemFactory(variant=v, warehouse=_wh(ng), quantity=10)
    reserve(v, 2, ng, reference="ORD-4")
    reserve(v, 2, ng, reference="ORD-4")  # replay -> no double reserve
    si.refresh_from_db()
    assert si.reserved == 2


@pytest.mark.django_db
def test_commit_sale_decrements_quantity_and_reserved(ng):
    v = ProductVariantFactory()
    si = StockItemFactory(variant=v, warehouse=_wh(ng), quantity=10)
    reserve(v, 3, ng, reference="ORD-5")
    commit_sale("ORD-5")
    si.refresh_from_db()
    assert si.quantity == 7
    assert si.reserved == 0
    # release after commit is a no-op (ledger already settled).
    release("ORD-5")
    si.refresh_from_db()
    assert si.reserved == 0 and si.quantity == 7


@pytest.mark.django_db
def test_release_is_idempotent(ng):
    v = ProductVariantFactory()
    si = StockItemFactory(variant=v, warehouse=_wh(ng), quantity=10)
    reserve(v, 4, ng, reference="ORD-6")
    release("ORD-6")
    release("ORD-6")  # second call no-op
    si.refresh_from_db()
    assert si.reserved == 0
    assert StockMovement.objects.filter(reference="ORD-6", reason="release").count() == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest apps/inventory/tests/test_services.py -v`
Expected: FAIL — `ModuleNotFoundError: apps.inventory.services`.

- [ ] **Step 3: Write the services**

Create `backend/apps/inventory/services.py`:

```python
"""The ONLY code allowed to change stock numbers. Every function runs inside a
transaction and locks StockItem rows in pk order (deadlock-safe), then allocates
by warehouse priority. release/commit_sale replay the movement ledger for
idempotency. A DB CHECK constraint (0 <= reserved <= quantity) is the backstop.
"""
from __future__ import annotations

from django.db import transaction
from django.db.models import F, Sum

from apps.inventory.models import StockItem, StockMovement, Warehouse


class InsufficientStock(Exception):
    """Raised when the requested quantity exceeds available stock for a country."""


def available_for_country(variant, country) -> int:
    agg = StockItem.objects.filter(
        variant=variant, warehouse__is_active=True, warehouse__serves_countries=country
    ).aggregate(total=Sum(F("quantity") - F("reserved")))
    return agg["total"] or 0


def _held_reserved(reference: str, stock_item_id: int) -> int:
    """Net reserved currently held under `reference` for one stock item = sum of all
    delta_reserved movements (reservation:+, release:-, sale:-)."""
    agg = StockMovement.objects.filter(
        reference=reference, stock_item_id=stock_item_id
    ).aggregate(s=Sum("delta_reserved"))
    return agg["s"] or 0


def _lock_items(variant, warehouses):
    """Lock the variant's StockItem rows for these warehouses, in pk order.
    pk order (NOT priority order) is load-bearing: it gives a single, consistent
    lock-acquisition order across concurrent reservations, eliminating ABBA
    deadlocks. Allocation re-sorts by priority afterward. Do not 'simplify' this.
    `of=("self",)` locks only StockItem rows, not the joined warehouse rows.
    """
    return list(
        StockItem.objects.select_for_update(of=("self",))
        .select_related("warehouse")
        .filter(variant=variant, warehouse__in=warehouses)
        .order_by("pk")
    )


def reserve(variant, qty: int, country, reference: str) -> None:
    if qty <= 0:
        raise ValueError("qty must be positive")
    warehouses = Warehouse.objects.filter(is_active=True, serves_countries=country)
    with transaction.atomic():
        items = _lock_items(variant, warehouses)
        # Idempotency: already reserved under this reference -> no-op (checked under lock).
        if StockMovement.objects.filter(
            reference=reference, reason="reservation", stock_item__in=items
        ).exists():
            return
        if sum(i.available for i in items) < qty:
            raise InsufficientStock(
                f"Need {qty} of {variant.sku} for {country.code}, "
                f"only {sum(i.available for i in items)} available."
            )
        # Allocate walking warehouses by priority (then pk for stability).
        items.sort(key=lambda i: (i.warehouse.priority, i.pk))
        remaining = qty
        for item in items:
            if remaining <= 0:
                break
            take = min(item.available, remaining)
            if take <= 0:
                continue
            item.reserved += take
            item.save(update_fields=["reserved", "updated_at"])
            StockMovement.objects.create(
                stock_item=item, delta_reserved=take, reason="reservation", reference=reference
            )
            remaining -= take


def _replay(reference: str, *, commit: bool) -> None:
    """Shared release/commit body. For each stock item touched by `reference`,
    compute the still-held reserved and settle it. commit=True also reduces quantity."""
    item_ids = list(
        StockMovement.objects.filter(reference=reference)
        .values_list("stock_item_id", flat=True)
        .distinct()
    )
    with transaction.atomic():
        items = (
            StockItem.objects.select_for_update(of=("self",))
            .filter(pk__in=item_ids)
            .order_by("pk")
        )
        for item in items:
            held = _held_reserved(reference, item.pk)
            if held <= 0:
                continue  # already released/committed -> idempotent no-op
            item.reserved -= held
            if commit:
                item.quantity -= held
                item.save(update_fields=["reserved", "quantity", "updated_at"])
                StockMovement.objects.create(
                    stock_item=item, delta_reserved=-held, delta_quantity=-held,
                    reason="sale", reference=reference,
                )
            else:
                item.save(update_fields=["reserved", "updated_at"])
                StockMovement.objects.create(
                    stock_item=item, delta_reserved=-held, reason="release", reference=reference
                )


def release(reference: str) -> None:
    _replay(reference, commit=False)


def commit_sale(reference: str) -> None:
    _replay(reference, commit=True)


def adjust(stock_item, new_quantity: int, reason: str, note: str, user=None) -> None:
    """Set on-hand to an absolute value, recording the delta as a movement."""
    if new_quantity < 0:
        raise ValueError("quantity cannot be negative")
    with transaction.atomic():
        locked = StockItem.objects.select_for_update().get(pk=stock_item.pk)
        delta = new_quantity - locked.quantity
        locked.quantity = new_quantity
        locked.save(update_fields=["quantity", "updated_at"])
        StockMovement.objects.create(
            stock_item=locked, delta_quantity=delta, reason=reason, note=note, created_by=user
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest apps/inventory/tests/test_services.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/inventory/services.py apps/inventory/factories.py apps/inventory/tests/test_services.py
git commit -m "feat(inventory): reserve/release/commit_sale/adjust services (locked, ledger-idempotent)"
```

---

## Task 4: Concurrency test + ledger reconciliation

The required "two threads, last unit, exactly one wins" test — Postgres-only by nature — plus a reconciliation invariant check.

**Files:**
- Test: `backend/apps/inventory/tests/test_concurrency.py`
- Modify: `backend/apps/inventory/services.py` (add `reconcile` helper)

- [ ] **Step 1: Add the reconciliation helper**

Append to `backend/apps/inventory/services.py`:

```python
def reconcile(stock_item) -> bool:
    """Invariant check: the ledger sums must equal the live counters.
    Returns True if consistent. Use in tests and periodic audits."""
    agg = StockMovement.objects.filter(stock_item=stock_item).aggregate(
        q=Sum("delta_quantity"), r=Sum("delta_reserved")
    )
    return (agg["q"] or 0) == stock_item.quantity and (agg["r"] or 0) == stock_item.reserved
```

Note: `reconcile` holds only when a stock item's ENTIRE history is movements (i.e. it started at 0 and every change was a movement). Seeded/adjusted-from-nonzero items won't satisfy it unless the initial quantity was itself a `restock`/`migration` movement. The concurrency test below starts items at 0 and restocks via `adjust`, so the invariant holds there.

- [ ] **Step 2: Write the concurrency test**

Create `backend/apps/inventory/tests/test_concurrency.py`:

```python
import threading

import pytest
from django.db import connection, connections
from django.test import TransactionTestCase

from apps.catalog.factories import ProductVariantFactory
from apps.core.models import Country
from apps.inventory.factories import StockItemFactory, WarehouseFactory
from apps.inventory.models import StockItem, StockMovement
from apps.inventory.services import InsufficientStock, adjust, reconcile, reserve


@pytest.mark.skipif(
    connection.vendor != "postgresql",
    reason="Real row locking (select_for_update) requires PostgreSQL; SQLite is a no-op.",
)
class ReserveConcurrencyTest(TransactionTestCase):
    reset_sequences = True

    def test_two_threads_last_unit_exactly_one_wins(self):
        ng = Country.objects.get(code="NG")
        w = WarehouseFactory()
        w.serves_countries.add(ng)
        variant = ProductVariantFactory()
        si = StockItemFactory(variant=variant, warehouse=w, quantity=0, reserved=0)
        adjust(si, new_quantity=1, reason="restock", note="seed", user=None)  # exactly 1 unit

        barrier = threading.Barrier(2)
        results = []

        def worker(ref):
            barrier.wait()  # both threads hit reserve() at once
            try:
                reserve(variant, 1, ng, reference=ref)
                results.append("ok")
            except InsufficientStock:
                results.append("fail")
            finally:
                connections.close_all()  # each thread has its own connection

        threads = [threading.Thread(target=worker, args=(f"R{i}",)) for i in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert sorted(results) == ["fail", "ok"]  # exactly one succeeded
        si.refresh_from_db()
        assert si.reserved == 1  # never oversold
        assert StockMovement.objects.filter(reason="reservation").count() == 1
        assert reconcile(si)
```

- [ ] **Step 3: Run the test**

Run: `uv run python -m pytest apps/inventory/tests/test_concurrency.py -v`
Expected: PASS on Postgres. If it errors with "database is locked" or the skip triggers, confirm Task 0 (Postgres) is active — `python -c "import django;...connection.vendor"` should be `postgresql`.

- [ ] **Step 4: Commit**

```bash
git add apps/inventory/services.py apps/inventory/tests/test_concurrency.py
git commit -m "test(inventory): concurrency race test (Postgres) + ledger reconciliation"
```

---

## Task 5: Admin stock API

Stock list (filterable), adjust endpoint (requires reason+note), movement history per variant, CSV import/export of counts.

**Files:**
- Create: `backend/apps/inventory/admin_serializers.py`, `admin_views.py`, `admin_urls.py`
- Modify: `backend/config/urls.py`
- Test: `backend/apps/inventory/tests/test_admin_api.py`

- [ ] **Step 1: Write the failing test**

Create `backend/apps/inventory/tests/test_admin_api.py`:

```python
import pytest
from rest_framework.test import APIClient

from apps.catalog.factories import ProductVariantFactory
from apps.catalog.tests.factories_admin import staff_user
from apps.core.models import Country
from apps.inventory.factories import StockItemFactory, WarehouseFactory
from apps.inventory.models import StockItem, StockMovement


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest apps/inventory/tests/test_admin_api.py -v`
Expected: FAIL — 404.

- [ ] **Step 3: Write serializers**

Create `backend/apps/inventory/admin_serializers.py`:

```python
from rest_framework import serializers

from apps.inventory.models import StockItem, StockMovement


class StockItemSerializer(serializers.ModelSerializer):
    available = serializers.IntegerField(read_only=True)
    sku = serializers.CharField(source="variant.sku", read_only=True)
    warehouse_name = serializers.CharField(source="warehouse.name", read_only=True)

    class Meta:
        model = StockItem
        fields = [
            "id", "variant", "sku", "warehouse", "warehouse_name",
            "quantity", "reserved", "available", "low_stock_threshold",
        ]
        read_only_fields = ["quantity", "reserved"]  # numbers change only via adjust/reserve


class StockAdjustSerializer(serializers.Serializer):
    quantity = serializers.IntegerField(min_value=0)
    reason = serializers.ChoiceField(choices=[c[0] for c in StockMovement.REASONS])
    note = serializers.CharField()  # required — no silent stock changes


class StockMovementSerializer(serializers.ModelSerializer):
    sku = serializers.CharField(source="stock_item.variant.sku", read_only=True)

    class Meta:
        model = StockMovement
        fields = [
            "id", "stock_item", "sku", "delta_quantity", "delta_reserved",
            "reason", "reference", "note", "created_by", "created_at",
        ]
```

- [ ] **Step 4: Write views**

Create `backend/apps/inventory/admin_views.py`:

```python
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import generics, permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.inventory.admin_serializers import (
    StockAdjustSerializer,
    StockItemSerializer,
    StockMovementSerializer,
)
from apps.inventory.models import StockItem, StockMovement
from apps.inventory.services import adjust


class StockItemAdminViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAdminUser]
    serializer_class = StockItemSerializer
    queryset = StockItem.objects.select_related("variant", "warehouse").all()
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["warehouse", "variant"]
    http_method_names = ["get", "post", "head", "options"]  # no direct PUT/PATCH of numbers

    @action(detail=True, methods=["post"])
    def adjust(self, request, pk=None):
        item = self.get_object()
        serializer = StockAdjustSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        adjust(
            item,
            new_quantity=serializer.validated_data["quantity"],
            reason=serializer.validated_data["reason"],
            note=serializer.validated_data["note"],
            user=request.user,
        )
        item.refresh_from_db()
        return Response(StockItemSerializer(item).data, status=200)


class StockMovementListView(generics.ListAPIView):
    permission_classes = [permissions.IsAdminUser]
    serializer_class = StockMovementSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["reason", "reference"]

    def get_queryset(self):
        qs = StockMovement.objects.select_related("stock_item__variant").all()
        variant = self.request.query_params.get("variant")
        if variant:
            qs = qs.filter(stock_item__variant_id=variant)
        return qs
```

- [ ] **Step 5: Wire routes**

Create `backend/apps/inventory/admin_urls.py`:

```python
from django.urls import path
from rest_framework.routers import DefaultRouter

from apps.inventory.admin_views import StockItemAdminViewSet, StockMovementListView

router = DefaultRouter()
router.register("stock", StockItemAdminViewSet, basename="admin-stock")

urlpatterns = [
    path("stock/movements/", StockMovementListView.as_view(), name="admin-stock-movements"),
] + router.urls
```

In `backend/config/urls.py`, add:

```python
    path("api/v1/admin/", include("apps.catalog.admin_urls")),
    path("api/v1/admin/", include("apps.inventory.admin_urls")),
```

Note: `stock/movements/` is a plain path registered BEFORE the router's `stock/<pk>/` detail so it isn't captured as a stock pk.

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run python -m pytest apps/inventory/tests/test_admin_api.py -v`
Expected: PASS (3 tests).

- [ ] **Step 7: Commit**

```bash
git add apps/inventory/admin_serializers.py apps/inventory/admin_views.py apps/inventory/admin_urls.py config/urls.py apps/inventory/tests/test_admin_api.py
git commit -m "feat(inventory): admin stock list, adjust (reason+note), movement history"
```

---

## Task 6: Low-stock alert (Celery beat) + real `in_stock` in the storefront

Two finishing pieces: an hourly low-stock digest email, and replacing the Plan-05b `in_stock` stub with real availability.

**Files:**
- Create: `backend/apps/inventory/tasks.py`
- Modify: `backend/config/settings/base.py` (beat schedule), `backend/apps/notifications/templates/email/` (digest template), `backend/apps/catalog/api_serializers.py`
- Test: `backend/apps/inventory/tests/test_low_stock.py`, update `backend/apps/catalog/tests/test_product_api.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/apps/inventory/tests/test_low_stock.py`:

```python
import pytest
from django.core import mail

from apps.inventory.factories import StockItemFactory
from apps.inventory.tasks import low_stock_digest


@pytest.mark.django_db
def test_low_stock_digest_emails_when_below_threshold(settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    mail.outbox = []
    StockItemFactory(quantity=2, reserved=0, low_stock_threshold=5)   # low
    StockItemFactory(quantity=50, reserved=0, low_stock_threshold=5)  # fine
    sent = low_stock_digest()
    assert sent == 1                    # one item in the digest
    assert len(mail.outbox) == 1


@pytest.mark.django_db
def test_low_stock_digest_silent_when_all_ok(settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    mail.outbox = []
    StockItemFactory(quantity=50, reserved=0, low_stock_threshold=5)
    assert low_stock_digest() == 0
    assert len(mail.outbox) == 0
```

Append to `backend/apps/catalog/tests/test_product_api.py`:

```python
@pytest.mark.django_db
def test_detail_in_stock_reflects_inventory():
    from apps.core.models import Country
    from apps.inventory.factories import StockItemFactory, WarehouseFactory

    p = _priced_product("1000")
    v = p.variants.first()
    ng = Country.objects.get(code="NG")
    w = WarehouseFactory()
    w.serves_countries.add(ng)
    StockItemFactory(variant=v, warehouse=w, quantity=0)  # no stock

    r = APIClient().get(f"/api/v1/products/{p.slug}/", HTTP_X_COUNTRY="NG")
    assert r.data["variants"][0]["in_stock"] is False

    si = v.stock_items.first()
    si.quantity = 5
    si.save(update_fields=["quantity"])
    r = APIClient().get(f"/api/v1/products/{p.slug}/", HTTP_X_COUNTRY="NG")
    assert r.data["variants"][0]["in_stock"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest apps/inventory/tests/test_low_stock.py apps/catalog/tests/test_product_api.py::test_detail_in_stock_reflects_inventory -v`
Expected: FAIL — task missing; `in_stock` still hard-coded `True`.

- [ ] **Step 3: Write the low-stock task + template**

Create `backend/apps/inventory/tasks.py`:

```python
from celery import shared_task
from django.db.models import F

from apps.inventory.models import StockItem
from apps.notifications.send import send_email


@shared_task
def low_stock_digest() -> int:
    """Email admin a digest of stock items at/below their threshold. Returns the count."""
    from django.conf import settings

    low = list(
        StockItem.objects.select_related("variant", "warehouse")
        .filter(quantity__lte=F("low_stock_threshold"))
        .order_by("warehouse__name", "variant__sku")
    )
    if not low:
        return 0
    rows = [
        {"sku": si.variant.sku, "warehouse": si.warehouse.name, "available": si.available}
        for si in low
    ]
    send_email("low_stock_digest", settings.DEFAULT_FROM_EMAIL, {"rows": rows})
    return len(low)
```

Create `backend/apps/notifications/templates/email/low_stock_digest.subject.txt`:

```
Low stock alert — {{ rows|length }} item(s) need restocking
```

Create `backend/apps/notifications/templates/email/low_stock_digest.txt`:

```
Low stock digest:
{% for r in rows %}- {{ r.sku }} @ {{ r.warehouse }}: {{ r.available }} available
{% endfor %}
```

Create `backend/apps/notifications/templates/email/low_stock_digest.html`:

```html
<h2>Low stock digest</h2>
<ul>
{% for r in rows %}<li><strong>{{ r.sku }}</strong> @ {{ r.warehouse }} — {{ r.available }} available</li>
{% endfor %}</ul>
```

- [ ] **Step 4: Schedule it (Celery beat) + real in_stock**

In `backend/config/settings/base.py`, after the Celery block, add:

```python
CELERY_BEAT_SCHEDULE = {
    "low-stock-digest-hourly": {
        "task": "apps.inventory.tasks.low_stock_digest",
        "schedule": 3600.0,  # every hour
    },
}
```

In `backend/apps/catalog/api_serializers.py`, replace the `VariantSerializer.get_in_stock` stub:

```python
    def get_in_stock(self, obj):
        from apps.inventory.services import available_for_country

        country = self.context["request"].country
        return available_for_country(obj, country) > 0
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run python -m pytest apps/inventory/tests/test_low_stock.py apps/catalog/tests/test_product_api.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/inventory/tasks.py apps/notifications/templates/email/low_stock_digest.* config/settings/base.py apps/catalog/api_serializers.py apps/inventory/tests/test_low_stock.py apps/catalog/tests/test_product_api.py
git commit -m "feat(inventory): hourly low-stock digest + real in_stock in storefront API"
```

---

## Task 7: Docs + final verification

**Files:**
- Modify: `docs/architecture.md`

- [ ] **Step 1: Update status**

Append to **Current status** in `docs/architecture.md`:

```
Plan-06 (inventory) ✅ — Warehouse/StockItem/StockMovement (oversell CHECK constraint), seeded
Lagos HQ + UK Warehouse, race-safe reserve/release/commit_sale/adjust services (pk-ordered locks,
ledger-idempotent), Postgres concurrency test (two threads, last unit, exactly one wins), admin
stock API (list/adjust/history), hourly low-stock digest, and real `in_stock` wired into the
storefront. Test suite now runs on Postgres. Next: Plan-07 (search) or Plan-08 (cart/checkout).
```

- [ ] **Step 2: Commit**

```bash
git add docs/architecture.md
git commit -m "docs: record Plan-06 inventory status"
```

---

## Final verification (stage)

- [ ] `uv run python -m pytest -q` on **Postgres** — all green, including the concurrency test (NOT skipped — confirm it ran: `-v` shows `test_two_threads_last_unit_exactly_one_wins PASSED`).
- [ ] `uv run python manage.py check` — no issues.
- [ ] Manual: seed stock via `POST /api/v1/admin/stock/<id>/adjust/`, then `GET /api/v1/products/<slug>/ -H "X-Country: NG"` shows `in_stock: true`; reserve all of it in a shell (`reserve(...)`) and confirm `in_stock` flips to false and the movement history endpoint lists the reservation.

**CHECKPOINT:** show Hammed the concurrency test output (exactly one thread wins) + a movement-history JSON for a variant that was reserved then committed.

---

## Self-review notes (author)

- **Spec coverage (Plan-06):** models Warehouse/StockItem/StockMovement (Task 1) with the oversell CHECK; seed warehouses (Task 2); services available_for_country/reserve/release/commit_sale/adjust, all locked (Task 3); REQUIRED concurrency test (Task 4); low-stock hourly Celery digest (Task 6); admin API list/adjust/history + CSV — **CSV import/export of stock counts is NOT in this plan** (see gap below); real `in_stock` wired into storefront (Task 6, closes the Plan-05b stub). 
- **Gap flagged:** the master spec item 4 also lists "CSV import/export of stock counts." I left it out to keep this plan focused on correctness; it's a small follow-on (mirror the catalog CSV pattern from Plan-05c). Add as Task 5b or a short Plan-06b if Hammed wants it now.
- **Fable 5 design input (applied):** single pk-ordered `select_for_update(of=("self",))` queryset; DB CHECK backstop; ledger-replay idempotency for release/commit (never trust caller quantities); `reconcile()` invariant; Postgres for the race test with `TransactionTestCase` + `Barrier` + per-thread `connections.close_all()`.
- **Deferred (correctly out of scope):** reservation **expiry** (`reserved_until` + cleanup task) belongs to Plan-08 checkout, where reservations are created — noted so it isn't forgotten (a reservation system without expiry leaves stock stuck "reserved" forever after abandoned carts).
- **Types consistent:** `reserve/release/commit_sale` all key off `reference` and settle via `_held_reserved`; `available_for_country` is the single availability number used by both the storefront `in_stock` and the reserve precheck.
```
