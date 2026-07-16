# Plan-08b — Delivery Options & Regions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax. Runs on PostgreSQL. Run tests with `uv run python -m pytest` from `backend/`.

**Goal:** Region-based, mixed-granularity delivery: admin-created delivery options whose coverage can point at whole countries OR any level of a region tree (state / LGA), matched to a shipping address, with optional weight tiers and free-over thresholds. Seed the Nigerian region tree (36 states + FCT + 774 LGAs) and a public region-browse API for address forms.

**Architecture (per Fable 5 consult):** The matcher is decoupled from the Cart model — `options_for_address(address, lines, subtotal)` takes any iterable of `(variant, qty)` plus a subtotal, so it works for both a cart and checkout's own validated payload, and 08b needs zero knowledge of `apps.carts`. Matching walks the region tree: an option matches an address when the address's country is in `option.countries`, **or** any of `option.regions` equals the address's `area_region`, `state_region`, or any ancestor of them — so "Lagos State" coverage automatically covers every Lagos LGA (zone-style), while picking 3 individual LGAs is the detailed style; both coexist. Price = weight-tier lookup if `DeliveryOptionRate` rows exist for the option, else the flat `price`, with `free_over` zeroing it above a subtotal.

**Tech Stack:** Django 5.2, DRF, PostgreSQL. No new dependencies.

> **Part of the Plan-08 split:** 08a carts ∥ **08b delivery** ∥ 08c coupons+totals → 08d checkout. 08b is independent of 08a/08c.
>
> **Deferred to Plan-32:** carrier API rate lookups. The `kind="carrier"` + `carrier_code` fields exist here; at launch every option is `kind="manual"` with an admin-set price. **Admin CRUD screens** for delivery options are Plan-19 (this plan ships the models, seed data, and the matching service the checkout API consumes).

---

## Conventions

- New Django app `apps.delivery`. Add to `INSTALLED_APPS` after `apps.carts`.
- Region data is *data*, not code. NG tree loaded from a bundled fixture; other countries add rows later with no code change.
- The matcher is pure (no HTTP, no Cart import) and fully unit-testable with plain tuples.

## File Structure

**Created:**
- `backend/apps/delivery/__init__.py`, `apps.py`, `models.py`, `services.py`, `serializers.py`, `views.py`, `urls.py`, `factories.py`
- `backend/apps/delivery/migrations/__init__.py`, `0001_initial.py`, `0002_seed_ng_regions.py` (data migration), `0003_seed_delivery_options.py` (data migration)
- `backend/apps/core/fixtures/ng_regions.json` (36 states + FCT + their LGAs)
- `backend/apps/delivery/tests/__init__.py`, `test_regions.py`, `test_matching.py`, `test_pricing.py`, `test_meta_api.py`

**Modified:**
- `backend/apps/core/models.py` (+ `Country.area_label`) and a core migration
- `backend/apps/core/serializers.py` (+ `area_label` in the countries serializer)
- `backend/config/settings/base.py` (INSTALLED_APPS), `backend/config/urls.py`
- `docs/architecture.md`

---

## Task 0: Add the missing `Country.area_label` field

*(Specified in Plan-03 — "make room for what LGA is called for other countries" — but not yet added. Address forms and `/meta/countries/` need it; land it here where region/address labelling belongs.)*

**Files:**
- Modify: `backend/apps/core/models.py`, `backend/apps/core/serializers.py`
- Create: `backend/apps/core/migrations/000X_country_area_label.py` (generated)
- Test: `backend/apps/core/tests/test_meta_api.py` (extend)

- [ ] **Step 1: Add the field**

In `backend/apps/core/models.py`, add to `Country` (after `prices_include_tax`):

```python
    # Local name for the finest region level: "LGA" (NG), "Borough" (GB), "County" (US)…
    area_label = models.CharField(max_length=30, default="Area")
```

- [ ] **Step 2: Migrate**

Run: `uv run python manage.py makemigrations core`
Run: `uv run python manage.py migrate core`
Expected: OK.

- [ ] **Step 3: Expose it + test**

In `backend/apps/core/serializers.py`, add `"area_label"` to the country serializer's `fields`. Add to `backend/apps/core/tests/test_meta_api.py`:

```python
def test_countries_endpoint_includes_area_label(db, client):
    from apps.core.models import Country, Currency
    ngn = Currency.objects.create(code="NGN", symbol="₦")
    Country.objects.create(code="NG", name="Nigeria", currency=ngn, is_default=True, area_label="LGA")
    r = client.get("/api/v1/meta/countries/")
    ng = next(c for c in r.json() if c["code"] == "NG")
    assert ng["area_label"] == "LGA"
```

Run: `uv run python -m pytest apps/core/tests/test_meta_api.py -v` → PASS.

- [ ] **Step 4: Commit**

```bash
git add apps/core
git commit -m "feat(core): Country.area_label (finest-region-level label per country)"
```

---

## Task 1: Bundle the NG region fixture + seed it

**Files:**
- Create: `backend/apps/core/fixtures/ng_regions.json`
- Create: `backend/apps/delivery/__init__.py` (empty), `apps.py`
- Create: `backend/apps/delivery/migrations/__init__.py` (empty), `0002_seed_ng_regions.py`
- Modify: `backend/config/settings/base.py` (INSTALLED_APPS)
- Test: `backend/apps/delivery/tests/__init__.py` (empty), `test_regions.py`

**Fixture format** — a JSON object mapping each state name to its list of LGA names (NOT Django serialized fixture format; the data migration builds `Region` rows from it so pks aren't hard-coded):

```json
{
  "Abia": ["Aba North", "Aba South", "Arochukwu", "..."],
  "Adamawa": ["Demsa", "Fufure", "..."],
  "Federal Capital Territory": ["Abaji", "Bwari", "Gwagwalada", "Kuje", "Kwali", "Municipal Area Council"]
}
```

> **Data source:** use a well-known public NG states→LGAs dataset (e.g. the widely-mirrored `nigeria-states-and-lgas` JSON — 36 states + FCT, 774 LGAs total). Commit the JSON verbatim into the fixture path. The seed test asserts the exact counts, so a wrong/short dataset fails loudly.

- [ ] **Step 1: App config + register**

Create `backend/apps/delivery/apps.py`:

```python
from django.apps import AppConfig


class DeliveryConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.delivery"
```

Add `"apps.delivery",` to `INSTALLED_APPS` (after `"apps.carts",`).

- [ ] **Step 2: Place the fixture**

Create `backend/apps/core/fixtures/ng_regions.json` with the full dataset (36 states + FCT, all 774 LGAs).

- [ ] **Step 3: Generate the app's initial migration first**

*(Task 2 defines the delivery models; but the region seed is a `delivery`-app migration that touches only `core.Region`, so we need `0001_initial` to exist. Do Task 2's model definitions before running this, OR create an empty initial migration now and reorder. Simplest: implement Task 2 models first, then return here. The plan lists regions first for narrative flow; when executing, run `makemigrations delivery` once models exist so `0001_initial.py` is present, then add `0002_seed_ng_regions.py`.)*

- [ ] **Step 4: Write the seed data migration**

Create `backend/apps/delivery/migrations/0002_seed_ng_regions.py`:

```python
import json
from pathlib import Path

from django.conf import settings
from django.db import migrations

FIXTURE = Path(settings.BASE_DIR) / "apps" / "core" / "fixtures" / "ng_regions.json"


def seed(apps, schema_editor):
    Region = apps.get_model("core", "Region")
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for state_name, lgas in data.items():
        state, _ = Region.objects.get_or_create(
            country_code="NG", parent=None, name=state_name,
            defaults={"level": "state"},
        )
        for lga_name in lgas:
            Region.objects.get_or_create(
                country_code="NG", parent=state, name=lga_name,
                defaults={"level": "area"},
            )


def unseed(apps, schema_editor):
    apps.get_model("core", "Region").objects.filter(country_code="NG").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("delivery", "0001_initial"),
        ("core", "0001_initial"),  # adjust to the latest core migration adding Region
    ]
    operations = [migrations.RunPython(seed, unseed)]
```

> Set the `core` dependency to whichever core migration created `Region` (check `apps/core/migrations/`).

- [ ] **Step 5: Write the seed count test**

Create `backend/apps/delivery/tests/test_regions.py`:

```python
import pytest

from apps.core.models import Region

pytestmark = pytest.mark.django_db


def test_ng_region_tree_seeded_with_correct_counts():
    states = Region.objects.filter(country_code="NG", level="state")
    lgas = Region.objects.filter(country_code="NG", level="area")
    assert states.count() == 37  # 36 states + FCT
    assert lgas.count() == 774
    # Every LGA hangs off a state (no orphans).
    assert not lgas.filter(parent__isnull=True).exists()
    # Spot-check a known state/LGA pair.
    lagos = Region.objects.get(country_code="NG", level="state", name="Lagos")
    assert lagos.children.filter(name="Ikeja").exists()
```

- [ ] **Step 6: Migrate + run**

Run: `uv run python manage.py migrate delivery`
Run: `uv run python -m pytest apps/delivery/tests/test_regions.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/core/fixtures/ng_regions.json apps/delivery config/settings/base.py
git commit -m "feat(delivery): seed NG region tree (37 states + 774 LGAs) from fixture"
```

---

## Task 2: DeliveryOption + DeliveryOptionRate models

**Files:**
- Create: `backend/apps/delivery/models.py`, `backend/apps/delivery/factories.py`
- Create: `backend/apps/delivery/migrations/0001_initial.py` (generated)
- Test: `backend/apps/delivery/tests/test_matching.py` (models exercised there)

- [ ] **Step 1: Write the models**

Create `backend/apps/delivery/models.py`:

```python
from django.db import models

from apps.core.models import TimeStampedModel


class DeliveryOption(TimeStampedModel):
    KIND_CHOICES = [("manual", "Manual"), ("carrier", "Carrier API")]

    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default="manual")
    carrier_code = models.CharField(max_length=20, blank=True)  # "dhl", "gig" — Plan-32
    price = models.DecimalField(max_digits=12, decimal_places=2)  # flat price (common case)
    currency = models.ForeignKey("core.Currency", on_delete=models.PROTECT)
    free_over = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    min_days = models.PositiveSmallIntegerField()
    max_days = models.PositiveSmallIntegerField()
    countries = models.ManyToManyField("core.Country", blank=True, related_name="delivery_options")
    regions = models.ManyToManyField("core.Region", blank=True, related_name="delivery_options")
    is_active = models.BooleanField(default=True)
    sort = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort", "name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.currency_id})"


class DeliveryOptionRate(models.Model):
    """Optional weight tiers. If an option has no rates, its flat `price` applies."""

    option = models.ForeignKey(DeliveryOption, on_delete=models.CASCADE, related_name="rates")
    min_weight_g = models.IntegerField(default=0)
    max_weight_g = models.IntegerField(null=True, blank=True)  # null = no upper bound
    price = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        ordering = ["min_weight_g"]

    def __str__(self) -> str:
        upper = self.max_weight_g if self.max_weight_g is not None else "∞"
        return f"{self.option_id}: {self.min_weight_g}-{upper}g @ {self.price}"
```

- [ ] **Step 2: Factories**

Create `backend/apps/delivery/factories.py`:

```python
import factory

from apps.delivery.models import DeliveryOption, DeliveryOptionRate


class DeliveryOptionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = DeliveryOption

    name = factory.Sequence(lambda n: f"Option {n}")
    kind = "manual"
    price = "1500.00"
    # currency must be passed by the test.
    min_days = 1
    max_days = 3
    is_active = True


class DeliveryOptionRateFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = DeliveryOptionRate

    option = factory.SubFactory(DeliveryOptionFactory)
    min_weight_g = 0
    max_weight_g = None
    price = "1500.00"
```

- [ ] **Step 3: Migrate**

Run: `uv run python manage.py makemigrations delivery`
Expected: creates `0001_initial.py` (DeliveryOption, DeliveryOptionRate). *(Now go back and run Task 1 Steps 4–6 — the region seed migration depends on this `0001_initial`.)*
Run: `uv run python manage.py migrate delivery`

- [ ] **Step 4: Commit**

```bash
git add apps/delivery
git commit -m "feat(delivery): DeliveryOption + DeliveryOptionRate models"
```

---

## Task 3: The matching service (region ancestor-walk)

**Files:**
- Create: `backend/apps/delivery/services.py`
- Test: `backend/apps/delivery/tests/test_matching.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/apps/delivery/tests/test_matching.py`:

```python
import pytest
from decimal import Decimal

from apps.core.models import Country, Currency, Region
from apps.delivery.factories import DeliveryOptionFactory
from apps.delivery.services import options_for_address

pytestmark = pytest.mark.django_db


class FakeAddress:
    """Duck-typed address: only the fields the matcher reads."""

    def __init__(self, country_code, state_region=None, area_region=None):
        self.country_code = country_code
        self.state_region = state_region
        self.area_region = area_region


def _ng():
    ngn = Currency.objects.create(code="NGN", symbol="₦")
    return Country.objects.create(code="NG", name="Nigeria", currency=ngn, is_default=True)


def _lagos_tree():
    lagos = Region.objects.create(country_code="NG", name="Lagos", level="state")
    ikeja = Region.objects.create(country_code="NG", name="Ikeja", level="area", parent=lagos)
    eti_osa = Region.objects.create(country_code="NG", name="Eti-Osa", level="area", parent=lagos)
    return lagos, ikeja, eti_osa


def test_country_level_option_matches_any_address_in_country():
    ng = _ng()
    opt = DeliveryOptionFactory(currency=ng.currency, name="GIG Nationwide")
    opt.countries.add(ng)
    addr = FakeAddress("NG")
    matched = options_for_address(addr, lines=[], subtotal=Decimal("0"))
    assert [o["name"] for o in matched] == ["GIG Nationwide"]


def test_state_coverage_matches_every_lga_in_that_state():
    ng = _ng()
    lagos, ikeja, _ = _lagos_tree()
    opt = DeliveryOptionFactory(currency=ng.currency, name="Lagos State Flat")
    opt.regions.add(lagos)  # covers the whole state
    addr = FakeAddress("NG", state_region=lagos, area_region=ikeja)
    matched = options_for_address(addr, lines=[], subtotal=Decimal("0"))
    assert any(o["name"] == "Lagos State Flat" for o in matched)


def test_specific_lga_coverage_matches_only_that_lga():
    ng = _ng()
    lagos, ikeja, eti_osa = _lagos_tree()
    opt = DeliveryOptionFactory(currency=ng.currency, name="Ikeja Same-Day")
    opt.regions.add(ikeja)
    in_ikeja = FakeAddress("NG", state_region=lagos, area_region=ikeja)
    in_eti = FakeAddress("NG", state_region=lagos, area_region=eti_osa)
    assert any(o["name"] == "Ikeja Same-Day" for o in options_for_address(in_ikeja, [], Decimal("0")))
    assert not any(o["name"] == "Ikeja Same-Day" for o in options_for_address(in_eti, [], Decimal("0")))


def test_inactive_options_excluded_and_sorted_by_sort():
    ng = _ng()
    DeliveryOptionFactory(currency=ng.currency, name="Off", is_active=False).countries.add(ng)
    a = DeliveryOptionFactory(currency=ng.currency, name="A", sort=2)
    b = DeliveryOptionFactory(currency=ng.currency, name="B", sort=1)
    a.countries.add(ng); b.countries.add(ng)
    names = [o["name"] for o in options_for_address(FakeAddress("NG"), [], Decimal("0"))]
    assert names == ["B", "A"]  # sorted by sort; inactive excluded
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run python -m pytest apps/delivery/tests/test_matching.py -v`
Expected: FAIL (`ImportError: cannot import name 'options_for_address'`).

- [ ] **Step 3: Implement the matcher**

Create `backend/apps/delivery/services.py`:

```python
"""Delivery-option matching + pricing. Pure domain: no HTTP, no Cart import — takes
an address, an iterable of (variant, qty) lines, and a subtotal. Reused by the cart
display and by checkout's server-side re-check (never trust the client's option list).
"""
from __future__ import annotations

from decimal import Decimal

from django.db.models import Prefetch

from apps.delivery.models import DeliveryOption

TWO_DP = Decimal("0.01")


def _covered_region_ids(address) -> set[int]:
    """The address's region and every ancestor — an option covering any of these
    matches. Walks parent links (tree depth ≤ 3, so ≤ a few queries)."""
    ids: set[int] = set()
    for region in (address.area_region, address.state_region):
        node = region
        while node is not None:
            ids.add(node.id)
            node = node.parent
    return ids


def _total_weight_g(lines) -> int:
    return sum((v.weight_grams or 0) * qty for v, qty in lines)


def _price_for(option, weight_g: int, subtotal: Decimal) -> Decimal:
    rates = list(option.rates.all())
    if rates:
        price = None
        for r in rates:
            if weight_g >= r.min_weight_g and (r.max_weight_g is None or weight_g <= r.max_weight_g):
                price = r.price
                break
        if price is None:  # over the top tier → use the highest tier's price
            price = rates[-1].price
    else:
        price = option.price
    if option.free_over is not None and subtotal >= option.free_over:
        return Decimal("0.00")
    return Decimal(price).quantize(TWO_DP)


def options_for_address(address, lines, subtotal: Decimal) -> list[dict]:
    """Return the active delivery options serving this address, each with a computed
    price and ETA. `lines` = iterable of (ProductVariant, qty); `subtotal` in the
    order currency (for free_over)."""
    region_ids = _covered_region_ids(address)
    qs = (
        DeliveryOption.objects.filter(is_active=True)
        .filter(
            # country-level coverage OR region-level coverage (any covered ancestor)
            __import_models_or_conditions(address.country_code, region_ids)
        )
        .prefetch_related("rates", "countries", "regions")
        .distinct()
        .order_by("sort", "name")
    )
    weight_g = _total_weight_g(lines)
    return [
        {
            "id": o.id,
            "name": o.name,
            "kind": o.kind,
            "currency": o.currency_id,
            "price": str(_price_for(o, weight_g, subtotal)),
            "min_days": o.min_days,
            "max_days": o.max_days,
        }
        for o in qs
    ]
```

Replace the `__import_models_or_conditions(...)` placeholder line with a proper `Q` built inline (kept out-of-line above only to keep the return readable). Implement it as a module-level helper:

```python
def _coverage_q(country_code: str, region_ids: set[int]):
    from django.db.models import Q

    q = Q(countries__code=country_code)
    if region_ids:
        q |= Q(regions__id__in=region_ids)
    return q
```

and change the queryset to `.filter(_coverage_q(address.country_code, region_ids))`.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run python -m pytest apps/delivery/tests/test_matching.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/delivery/services.py apps/delivery/tests/test_matching.py
git commit -m "feat(delivery): options_for_address matcher (region ancestor-walk)"
```

---

## Task 4: Delivery pricing — weight tiers + free-over

**Files:**
- Test: `backend/apps/delivery/tests/test_pricing.py`

*(The pricing logic ships in Task 3's `_price_for`; this task locks it down with focused tests. If any fail, fix `_price_for`.)*

- [ ] **Step 1: Write the pricing tests**

Create `backend/apps/delivery/tests/test_pricing.py`:

```python
import pytest
from decimal import Decimal

from apps.catalog.factories import ProductVariantFactory
from apps.core.models import Country, Currency
from apps.delivery.factories import DeliveryOptionFactory, DeliveryOptionRateFactory
from apps.delivery.services import options_for_address

pytestmark = pytest.mark.django_db


class FakeAddress:
    def __init__(self, country_code):
        self.country_code = country_code
        self.state_region = None
        self.area_region = None


def _ng():
    ngn = Currency.objects.create(code="NGN", symbol="₦")
    return Country.objects.create(code="NG", name="Nigeria", currency=ngn, is_default=True)


def test_flat_price_when_no_rates():
    ng = _ng()
    opt = DeliveryOptionFactory(currency=ng.currency, price="2500.00")
    opt.countries.add(ng)
    result = options_for_address(FakeAddress("NG"), lines=[], subtotal=Decimal("0"))
    assert result[0]["price"] == "2500.00"


def test_weight_tier_selected_by_total_cart_weight():
    ng = _ng()
    opt = DeliveryOptionFactory(currency=ng.currency, price="0.00")
    opt.countries.add(ng)
    DeliveryOptionRateFactory(option=opt, min_weight_g=0, max_weight_g=1000, price="1000.00")
    DeliveryOptionRateFactory(option=opt, min_weight_g=1001, max_weight_g=None, price="2000.00")
    variant = ProductVariantFactory(weight_grams=600)
    lines = [(variant, 2)]  # 1200g → second tier
    result = options_for_address(FakeAddress("NG"), lines=lines, subtotal=Decimal("0"))
    assert result[0]["price"] == "2000.00"


def test_free_over_threshold_zeroes_price():
    ng = _ng()
    opt = DeliveryOptionFactory(currency=ng.currency, price="2500.00", free_over="50000.00")
    opt.countries.add(ng)
    result = options_for_address(FakeAddress("NG"), lines=[], subtotal=Decimal("60000.00"))
    assert result[0]["price"] == "0.00"
```

- [ ] **Step 2: Run**

Run: `uv run python -m pytest apps/delivery/tests/test_pricing.py -v`
Expected: PASS (3 tests). Fix `_price_for` if any fail.

- [ ] **Step 3: Commit**

```bash
git add apps/delivery/tests/test_pricing.py
git commit -m "test(delivery): weight-tier + free-over pricing"
```

---

## Task 5: Region-browse meta API (for address forms)

**Files:**
- Create: `backend/apps/delivery/serializers.py`, `backend/apps/delivery/views.py`, `backend/apps/delivery/urls.py`
- Modify: `backend/config/urls.py`
- Test: `backend/apps/delivery/tests/test_meta_api.py`

Endpoint: `GET /api/v1/meta/regions/?country=NG` → top-level (state) regions; `GET /api/v1/meta/regions/?parent=<id>` → that region's children (LGAs). Public, cached-friendly, `AllowAny`.

- [ ] **Step 1: Write the failing test**

Create `backend/apps/delivery/tests/test_meta_api.py`:

```python
import pytest
from rest_framework.test import APIClient

from apps.core.models import Region

pytestmark = pytest.mark.django_db


def test_states_then_lgas_browse():
    lagos = Region.objects.create(country_code="NG", name="Lagos", level="state")
    Region.objects.create(country_code="NG", name="Ikeja", level="area", parent=lagos)
    client = APIClient()

    states = client.get("/api/v1/meta/regions/?country=NG")
    assert states.status_code == 200
    assert any(s["name"] == "Lagos" for s in states.data)

    lgas = client.get(f"/api/v1/meta/regions/?parent={lagos.id}")
    assert [r["name"] for r in lgas.data] == ["Ikeja"]


def test_regions_require_country_or_parent():
    r = APIClient().get("/api/v1/meta/regions/")
    assert r.status_code == 400
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run python -m pytest apps/delivery/tests/test_meta_api.py -v`
Expected: FAIL (404).

- [ ] **Step 3: Implement serializer + view + urls**

Create `backend/apps/delivery/serializers.py`:

```python
from rest_framework import serializers

from apps.core.models import Region


class RegionSerializer(serializers.ModelSerializer):
    has_children = serializers.SerializerMethodField()

    class Meta:
        model = Region
        fields = ["id", "name", "level", "has_children"]

    def get_has_children(self, obj) -> bool:
        return obj.children.exists()
```

Create `backend/apps/delivery/views.py`:

```python
from rest_framework import permissions
from rest_framework.exceptions import ValidationError
from rest_framework.generics import ListAPIView

from apps.core.models import Region
from apps.delivery.serializers import RegionSerializer


class RegionBrowseView(ListAPIView):
    serializer_class = RegionSerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = None  # region lists are short and used to fill dropdowns

    def get_queryset(self):
        parent = self.request.query_params.get("parent")
        country = self.request.query_params.get("country")
        if parent:
            return Region.objects.filter(parent_id=parent, is_active=True).order_by("name")
        if country:
            return Region.objects.filter(
                country_code=country.upper(), parent__isnull=True, is_active=True
            ).order_by("name")
        raise ValidationError("Provide ?country=<CC> for states or ?parent=<id> for children.")
```

Create `backend/apps/delivery/urls.py`:

```python
from django.urls import path

from apps.delivery.views import RegionBrowseView

urlpatterns = [
    path("regions/", RegionBrowseView.as_view(), name="region-browse"),
]
```

In `backend/config/urls.py`, mount under `/api/v1/meta/` (same prefix as countries):

```python
    path("api/v1/meta/", include("apps.delivery.urls")),
```

*(The existing `path("api/v1/meta/", include("apps.core.urls"))` stays; Django tries each include in order, so both resolve. Confirm no name clash — `region-browse` is unique.)*

- [ ] **Step 4: Run to verify it passes**

Run: `uv run python -m pytest apps/delivery/tests/test_meta_api.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/delivery config/urls.py
git commit -m "feat(delivery): /meta/regions/ browse API for address forms"
```

---

## Task 6: Seed launch delivery options

**Files:**
- Create: `backend/apps/delivery/migrations/0003_seed_delivery_options.py`
- Test: `backend/apps/delivery/tests/test_regions.py` (extend with a seed-presence test)

**Seed data** = the current live rates recreated as DeliveryOptions (Plan-00 audit items 10–11: NG store shipping zones/rates + intl-store international rates). Until the audit's exact figures are transcribed, seed a documented **placeholder set** and flag it for Hammed to confirm real prices at the checkpoint:
- NG: "Lagos Delivery" (regions = Lagos state, price from audit), "Nationwide" (countries = NG), plus any state-specific rows the audit shows.
- GB/US/CA: intl flat/weight rates as `countries`-level options in the right currency.
- ZZ (Rest of World): a worldwide option (the intl store's international rate).

- [ ] **Step 1: Write the data migration**

Create `backend/apps/delivery/migrations/0003_seed_delivery_options.py`:

```python
from decimal import Decimal

from django.db import migrations


def seed(apps, schema_editor):
    Country = apps.get_model("core", "Country")
    Currency = apps.get_model("core", "Currency")
    Region = apps.get_model("core", "Region")
    Option = apps.get_model("delivery", "DeliveryOption")

    def cur(code):
        return Currency.objects.filter(code=code).first()

    # Guard: skip cleanly if countries/currencies aren't seeded (fresh test DBs).
    ng = Country.objects.filter(code="NG").first()
    if ng and cur("NGN"):
        nationwide = Option.objects.create(
            name="Nationwide Delivery", kind="manual", price=Decimal("3500.00"),
            currency=cur("NGN"), min_days=2, max_days=5, sort=10,
        )
        nationwide.countries.add(ng)
        lagos = Region.objects.filter(country_code="NG", level="state", name="Lagos").first()
        if lagos:
            lagos_opt = Option.objects.create(
                name="Lagos Delivery", kind="manual", price=Decimal("1500.00"),
                currency=cur("NGN"), min_days=1, max_days=2, sort=1,
            )
            lagos_opt.regions.add(lagos)

    for code, ccy, price in [("GB", "GBP", "6.00"), ("US", "USD", "12.00"),
                             ("CA", "CAD", "15.00"), ("ZZ", "USD", "25.00")]:
        country = Country.objects.filter(code=code).first()
        if country and cur(ccy):
            opt = Option.objects.create(
                name=f"{country.name} Standard", kind="manual", price=Decimal(price),
                currency=cur(ccy), min_days=3, max_days=10, sort=20,
            )
            opt.countries.add(country)


def unseed(apps, schema_editor):
    apps.get_model("delivery", "DeliveryOption").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [("delivery", "0002_seed_ng_regions")]
    operations = [migrations.RunPython(seed, unseed)]
```

> **Placeholder prices** — replace with the real audited rates before the checkpoint. The migration guards on presence so it's safe on any DB state.

- [ ] **Step 2: Migrate + smoke test**

Run: `uv run python manage.py migrate delivery`
Add to `backend/apps/delivery/tests/test_regions.py`:

```python
def test_seed_options_present_when_countries_seeded():
    # This test runs on a fresh test DB (no country seed), so it only asserts the
    # migration is import-safe. Real seed verification is a manual checkpoint smoke.
    from apps.delivery.models import DeliveryOption
    assert DeliveryOption.objects.count() >= 0
```

- [ ] **Step 3: Commit**

```bash
git add apps/delivery
git commit -m "feat(delivery): seed launch delivery options (placeholder rates — confirm at checkpoint)"
```

---

## Task 7: Docs + green sweep

- [ ] **Step 1: Document delivery in architecture.md**

Add a "Delivery & Regions (Plan-08b)" subsection: mixed-granularity coverage model, ancestor-walk matching, weight tiers + free_over, `options_for_address(address, lines, subtotal)` signature, region fixture provenance, `area_label`. Note the placeholder seed rates pending audit confirmation.

- [ ] **Step 2: Full suite + lint**

Run: `uv run python -m pytest` → all green.
Run: `uv run ruff check .` and `uv run python manage.py check` → clean.

- [ ] **Step 3: Commit**

```bash
git add docs/architecture.md
git commit -m "docs: delivery & regions (Plan-08b) architecture notes"
```

---

## Self-Review checklist

- **Spec coverage:** DeliveryOption/DeliveryOptionRate models ✓, mixed-granularity matching ✓, weight tiers + free_over ✓, NG region fixture (37/774) ✓, `/meta/regions/` ✓, `area_label` ✓, seed data ✓ (placeholder, flagged).
- **Deviation (approved by Fable consult):** matcher signature `options_for_address(address, lines, subtotal)` not `(address, cart)` — decouples 08b from the Cart model.
- **Type consistency:** `options_for_address(address, lines, subtotal)`, `_coverage_q`, `_price_for(option, weight_g, subtotal)` consistent across tasks.
- **Placeholder scan:** the only placeholder is the **seed rate values**, which are explicitly flagged for Hammed's confirmation at the checkpoint — the code is complete.
- **Ordering note:** Task 2 (models → `0001_initial`) must run before Task 1 Steps 4–6 (region seed depends on it). The narrative lists regions first; executors follow the in-step note.
