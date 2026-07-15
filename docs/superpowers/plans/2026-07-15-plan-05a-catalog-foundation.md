# Plan-05a — Catalog Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the catalog data layer — taxonomy (Category/Brand/Tag/Collection), Product + ProductVariant, media (images/videos) — **and activate the `pricing` app** (register it, migrate it, and add the full `resolve_price` DB tests that Plan-04 deferred). Plus test factories the later API plans build on.

**Architecture:** New `apps.catalog` app, single `models.py` to match the existing `core`/`accounts` convention. All models inherit `apps.core.models.TimeStampedModel`. `ProductVariant` is the anchor the `pricing.Price` FK finally resolves against, so this plan is where the pricing migration + real resolution tests become possible. **This plan is models + factories only** — the country-aware read APIs (`sellable_in`, product list/detail, caching, N+1 budgets) are Plan-05b; admin write + CSV are Plan-05c.

**Tech Stack:** Django 5.2, DRF (later plans), factory_boy 3.3, Pillow (new — required by `ImageField`), pytest + pytest-django. No API code in this plan.

---

## Conventions for this plan (read once)

- **Run tests:** `uv run python -m pytest ...` from `backend/` (bare `pytest` is blocked by app-control policy).
- **Migrations:** `uv run python manage.py makemigrations` / `migrate` from `backend/`. The local dev DB was rebuilt clean during Plan-04, so plain `makemigrations` works. If a `InconsistentMigrationHistory` error ever reappears, generate the file against a throwaway DB: `DATABASE_URL='sqlite:///:memory:' uv run python manage.py makemigrations <app>`.
- **Single `models.py`** per app (matches `core`/`accounts`). The master guide's "split into models/ if large" is optional; we keep one file for consistency.
- All models inherit `TimeStampedModel` (gives `created_at`/`updated_at`).

## File Structure

**Created:**
- `backend/apps/catalog/__init__.py`, `apps.py`, `models.py`, `admin.py`
- `backend/apps/catalog/migrations/__init__.py`, `0001_initial.py` (generated)
- `backend/apps/catalog/tests/__init__.py`, `test_taxonomy.py`, `test_product.py`, `test_media.py`
- `backend/apps/catalog/factories.py` — factory_boy factories (catalog + price)
- `backend/apps/catalog/tests/test_factories.py`
- `backend/apps/pricing/migrations/__init__.py`, `0001_initial.py` (generated when app is activated)
- `backend/apps/pricing/tests/test_resolve_price.py` — the deferred Plan-04 DB tests

**Modified:**
- `backend/pyproject.toml` — add `pillow`
- `backend/config/settings/base.py` — add `apps.catalog` and `apps.pricing` to `INSTALLED_APPS`
- `docs/architecture.md` — Plan-05a status

---

## Task 1: Add Pillow dependency (required by ImageField)

**Files:**
- Modify: `backend/pyproject.toml`

- [ ] **Step 1: Add the dependency**

Add `"pillow>=11.0"` to the `dependencies` array in `backend/pyproject.toml` (keep alphabetical-ish ordering; place after `psycopg`):

```toml
    "psycopg[binary]>=3.3.4",
    "pillow>=11.0",
    "redis>=8.0.1",
```

- [ ] **Step 2: Sync**

Run: `uv sync`
Expected: installs Pillow (and nothing else surprising).

- [ ] **Step 3: Verify import**

Run: `uv run python -c "import PIL; print(PIL.__version__)"`
Expected: prints a version (e.g. `11.x`).

- [ ] **Step 4: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock
git commit -m "chore(backend): add Pillow for ImageField support"
```

---

## Task 2: Catalog app + taxonomy models

Creates the app and the taxonomy models: `Category` (self-tree), `Brand`, `Tag`, `Collection`.

**Files:**
- Create: `backend/apps/catalog/__init__.py` (empty), `apps.py`, `models.py`
- Create: `backend/apps/catalog/tests/__init__.py` (empty), `test_taxonomy.py`
- Modify: `backend/config/settings/base.py`

- [ ] **Step 1: Write the failing test**

Create `backend/apps/catalog/tests/__init__.py` (empty) and `backend/apps/catalog/tests/test_taxonomy.py`:

```python
import pytest

from apps.catalog.models import Brand, Category, Collection, Tag


@pytest.mark.django_db
def test_category_tree_and_ancestors():
    skincare = Category.objects.create(name="Skincare", slug="skincare")
    face = Category.objects.create(name="Face", slug="face", parent=skincare)
    serums = Category.objects.create(name="Serums", slug="serums", parent=face)
    assert serums.parent == face
    assert [c.slug for c in serums.get_ancestors()] == ["skincare", "face"]
    assert list(skincare.children.all()) == [face]
    assert str(serums) == "Serums"


@pytest.mark.django_db
def test_slugs_unique():
    Brand.objects.create(name="Toke", slug="toke")
    with pytest.raises(Exception):
        Brand.objects.create(name="Toke 2", slug="toke")


@pytest.mark.django_db
def test_collection_rule_default_is_manual():
    c = Collection.objects.create(name="New Arrivals", slug="new-arrivals")
    assert c.rule == "manual"
    assert c.is_active is True


@pytest.mark.django_db
def test_tag_basic():
    t = Tag.objects.create(name="Vegan", slug="vegan")
    assert str(t) == "Vegan"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest apps/catalog/tests/test_taxonomy.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.catalog'`.

- [ ] **Step 3: Create the app package**

Create `backend/apps/catalog/__init__.py` (empty).

Create `backend/apps/catalog/apps.py`:

```python
from django.apps import AppConfig


class CatalogConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.catalog"
```

- [ ] **Step 4: Write the taxonomy models**

Create `backend/apps/catalog/models.py`:

```python
from django.db import models

from apps.core.models import TimeStampedModel


class Category(TimeStampedModel):
    name = models.CharField(max_length=150)
    slug = models.SlugField(max_length=170, unique=True)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.CASCADE, related_name="children"
    )
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to="catalog/categories/", blank=True, null=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    seo_title = models.CharField(max_length=255, blank=True)
    seo_description = models.TextField(blank=True)

    class Meta:
        verbose_name_plural = "categories"
        ordering = ["sort_order", "name"]

    def __str__(self) -> str:
        return self.name

    def get_ancestors(self):
        """Root-first list of ancestors (excludes self). Depth is small (<= 3)."""
        chain = []
        node = self.parent
        while node is not None:
            chain.append(node)
            node = node.parent
        return list(reversed(chain))


class Brand(TimeStampedModel):
    name = models.CharField(max_length=150)
    slug = models.SlugField(max_length=170, unique=True)
    logo = models.ImageField(upload_to="catalog/brands/", blank=True, null=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Tag(TimeStampedModel):
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=120, unique=True)

    def __str__(self) -> str:
        return self.name


class Collection(TimeStampedModel):
    RULES = [
        ("manual", "Manual"),
        ("new_arrivals", "New arrivals"),
        ("best_sellers", "Best sellers"),
        ("trending", "Trending"),
    ]

    name = models.CharField(max_length=150)
    slug = models.SlugField(max_length=170, unique=True)
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to="catalog/collections/", blank=True, null=True)
    is_active = models.BooleanField(default=True)
    rule = models.CharField(max_length=20, choices=RULES, default="manual")
    # M2M to Product added in Task 3 (after Product exists) — see note there.

    def __str__(self) -> str:
        return self.name
```

- [ ] **Step 5: Register the app**

In `backend/config/settings/base.py`, add `apps.catalog` to `INSTALLED_APPS` under the `# local` group:

```python
    # local
    "apps.core",
    "apps.accounts",
    "apps.notifications",
    "apps.catalog",
```

- [ ] **Step 6: Make + run migration, then run tests**

Run: `uv run python manage.py makemigrations catalog`
Expected: creates `apps/catalog/migrations/0001_initial.py` (Category, Brand, Tag, Collection).

Run: `uv run python -m pytest apps/catalog/tests/test_taxonomy.py -v`
Expected: PASS (4 tests).

- [ ] **Step 7: Commit**

```bash
git add apps/catalog/__init__.py apps/catalog/apps.py apps/catalog/models.py apps/catalog/tests/ apps/catalog/migrations/0001_initial.py config/settings/base.py
git commit -m "feat(catalog): taxonomy models (Category, Brand, Tag, Collection)"
```

---

## Task 3: Product + ProductVariant

Adds `Product` (with `available_countries` M2M, JSON specs/faqs) and `ProductVariant` (the anchor for pricing), plus the `Collection.products` M2M now that `Product` exists.

**Files:**
- Modify: `backend/apps/catalog/models.py`
- Test: `backend/apps/catalog/tests/test_product.py`

- [ ] **Step 1: Write the failing test**

Create `backend/apps/catalog/tests/test_product.py`:

```python
import pytest

from apps.catalog.models import Brand, Product, ProductVariant
from apps.core.models import Country


@pytest.mark.django_db
def test_product_defaults_and_variant_relation():
    brand = Brand.objects.create(name="Toke", slug="toke")
    p = Product.objects.create(name="Glow Serum", slug="glow-serum", brand=brand)
    assert p.status == "draft"          # default
    assert p.is_featured is False
    assert p.specs == []                # JSON default list
    assert p.faqs == []
    v = ProductVariant.objects.create(product=p, sku="GLOW-50", name="50ml", is_default=True)
    assert list(p.variants.all()) == [v]
    assert v.option_values == {}        # JSON default dict
    assert str(v) == "Glow Serum — 50ml"


@pytest.mark.django_db
def test_available_countries_empty_means_everywhere():
    p = Product.objects.create(name="X", slug="x")
    assert p.available_countries.count() == 0   # empty = available everywhere (interpreted in Plan-05b)


@pytest.mark.django_db
def test_available_countries_can_be_scoped():
    p = Product.objects.create(name="Y", slug="y")
    ng = Country.objects.get(code="NG")
    p.available_countries.add(ng)
    assert list(p.available_countries.all()) == [ng]


@pytest.mark.django_db
def test_sku_unique():
    p = Product.objects.create(name="Z", slug="z")
    ProductVariant.objects.create(product=p, sku="DUP", name="a")
    with pytest.raises(Exception):
        ProductVariant.objects.create(product=p, sku="DUP", name="b")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest apps/catalog/tests/test_product.py -v`
Expected: FAIL — `ImportError: cannot import name 'Product'`.

- [ ] **Step 3: Add the models**

Append to `backend/apps/catalog/models.py`:

```python
class Product(TimeStampedModel):
    STATUS = [("draft", "Draft"), ("active", "Active"), ("archived", "Archived")]

    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=280, unique=True)
    brand = models.ForeignKey(
        Brand, null=True, blank=True, on_delete=models.SET_NULL, related_name="products"
    )
    categories = models.ManyToManyField(Category, blank=True, related_name="products")
    tags = models.ManyToManyField(Tag, blank=True, related_name="products")
    description = models.TextField(blank=True)          # rich HTML
    short_description = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=STATUS, default="draft")
    is_featured = models.BooleanField(default=False)
    ingredients = models.TextField(blank=True)
    directions = models.TextField(blank=True)
    warnings = models.TextField(blank=True)
    specs = models.JSONField(default=list, blank=True)  # [{"label": .., "value": ..}]
    faqs = models.JSONField(default=list, blank=True)   # [{"q": .., "a": ..}]
    related = models.ManyToManyField("self", blank=True)
    available_countries = models.ManyToManyField(
        "core.Country", blank=True, related_name="products"
    )  # empty = everywhere (see Plan-05b sellable_in)
    seo_title = models.CharField(max_length=255, blank=True)
    seo_description = models.TextField(blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    legacy_source = models.CharField(max_length=50, blank=True)
    legacy_wp_id = models.IntegerField(null=True, blank=True)

    class Meta:
        ordering = ["-published_at", "name"]

    def __str__(self) -> str:
        return self.name


class ProductVariant(TimeStampedModel):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="variants")
    sku = models.CharField(max_length=64, unique=True)
    barcode = models.CharField(max_length=64, blank=True)
    name = models.CharField(max_length=120)             # e.g. "50ml"
    option_values = models.JSONField(default=dict, blank=True)  # {"Size": "50ml"}
    weight_grams = models.PositiveIntegerField(null=True, blank=True)
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["position", "id"]

    def __str__(self) -> str:
        return f"{self.product.name} — {self.name}"
```

Then add the `products` M2M to `Collection` (it was noted as deferred in Task 2). Modify the `Collection` class body — add this field after `rule`:

```python
    products = models.ManyToManyField(Product, blank=True, related_name="collections")
```

- [ ] **Step 4: Make + run migration, then run tests**

Run: `uv run python manage.py makemigrations catalog`
Expected: creates `0002_*` adding Product, ProductVariant, and the Collection.products M2M.

Run: `uv run python -m pytest apps/catalog/tests/test_product.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/catalog/models.py apps/catalog/migrations/0002_*.py apps/catalog/tests/test_product.py
git commit -m "feat(catalog): Product + ProductVariant + Collection.products"
```

---

## Task 4: Media models (ProductImage, ProductVideo)

**Files:**
- Modify: `backend/apps/catalog/models.py`
- Test: `backend/apps/catalog/tests/test_media.py`

- [ ] **Step 1: Write the failing test**

Create `backend/apps/catalog/tests/test_media.py`:

```python
import pytest

from apps.catalog.models import Product, ProductImage, ProductVideo, ProductVariant


@pytest.mark.django_db
def test_image_attaches_to_product_and_optional_variant():
    p = Product.objects.create(name="P", slug="p")
    v = ProductVariant.objects.create(product=p, sku="P-1", name="default", is_default=True)
    img = ProductImage.objects.create(product=p, image="catalog/products/x.jpg", alt="x", variant=v)
    img2 = ProductImage.objects.create(product=p, image="catalog/products/y.jpg", position=1)
    assert set(p.images.all()) == {img, img2}
    assert img.variant == v
    assert img2.variant is None


@pytest.mark.django_db
def test_video_ordering():
    p = Product.objects.create(name="P2", slug="p2")
    ProductVideo.objects.create(product=p, url="https://youtu.be/b", position=1)
    ProductVideo.objects.create(product=p, url="https://youtu.be/a", position=0)
    assert [v.url for v in p.videos.all()] == ["https://youtu.be/a", "https://youtu.be/b"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest apps/catalog/tests/test_media.py -v`
Expected: FAIL — `ImportError: cannot import name 'ProductImage'`.

- [ ] **Step 3: Add the models**

Append to `backend/apps/catalog/models.py`:

```python
class ProductImage(TimeStampedModel):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField(upload_to="catalog/products/")
    alt = models.CharField(max_length=255, blank=True)
    position = models.PositiveIntegerField(default=0)
    variant = models.ForeignKey(
        "ProductVariant", null=True, blank=True, on_delete=models.SET_NULL, related_name="images"
    )

    class Meta:
        ordering = ["position", "id"]

    def __str__(self) -> str:
        return f"{self.product.name} image #{self.position}"


class ProductVideo(TimeStampedModel):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="videos")
    url = models.URLField()
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["position", "id"]

    def __str__(self) -> str:
        return f"{self.product.name} video #{self.position}"
```

- [ ] **Step 4: Make + run migration, then run tests**

Run: `uv run python manage.py makemigrations catalog`
Expected: creates `0003_*` (ProductImage, ProductVideo).

Run: `uv run python -m pytest apps/catalog/tests/test_media.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/catalog/models.py apps/catalog/migrations/0003_*.py apps/catalog/tests/test_media.py
git commit -m "feat(catalog): ProductImage + ProductVideo"
```

---

## Task 5: Activate the pricing app + full resolve_price DB tests

Now that `catalog.ProductVariant` exists, register `apps.pricing`, generate its migration, and add the DB-backed `resolve_price` tests that Plan-04 deferred (country override beats currency default; expired window ignored; missing price → None; NG default).

**Files:**
- Modify: `backend/config/settings/base.py`
- Create: `backend/apps/pricing/migrations/__init__.py` (empty), `0001_initial.py` (generated)
- Create: `backend/apps/pricing/tests/test_resolve_price.py`

- [ ] **Step 1: Write the failing test**

Create `backend/apps/pricing/tests/test_resolve_price.py`:

```python
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.catalog.models import Product, ProductVariant
from apps.core.models import Country, Currency
from apps.pricing.models import Price
from apps.pricing.services import resolve_price


@pytest.fixture
def variant(db):
    p = Product.objects.create(name="Serum", slug="serum")
    return ProductVariant.objects.create(product=p, sku="S-1", name="50ml", is_default=True)


@pytest.mark.django_db
def test_returns_none_when_no_price(variant):
    ng = Country.objects.get(code="NG")
    assert resolve_price(variant, ng) is None


@pytest.mark.django_db
def test_currency_default_used_when_no_country_row(variant):
    ngn = Currency.objects.get(code="NGN")
    ng = Country.objects.get(code="NG")
    Price.objects.create(variant=variant, currency=ngn, country=None, amount=Decimal("5000.00"))
    rp = resolve_price(variant, ng)
    assert rp is not None
    assert rp.amount == Decimal("5000.00")
    assert rp.currency == "NGN"
    assert rp.tax_rate == Decimal("7.50")          # from NG
    assert rp.prices_include_tax is True


@pytest.mark.django_db
def test_country_override_beats_currency_default(variant):
    ngn = Currency.objects.get(code="NGN")
    ng = Country.objects.get(code="NG")
    Price.objects.create(variant=variant, currency=ngn, country=None, amount=Decimal("5000.00"))
    Price.objects.create(variant=variant, currency=ngn, country=ng, amount=Decimal("4500.00"))
    assert resolve_price(variant, ng).amount == Decimal("4500.00")


@pytest.mark.django_db
def test_expired_sale_window_is_ignored(variant):
    ngn = Currency.objects.get(code="NGN")
    ng = Country.objects.get(code="NG")
    now = timezone.now()
    # An expired windowed price + a plain price -> the plain one wins (expired ignored).
    Price.objects.create(
        variant=variant, currency=ngn, country=ng, amount=Decimal("3000.00"),
        starts_at=now - timezone.timedelta(days=10), ends_at=now - timezone.timedelta(days=5),
    )
    Price.objects.create(variant=variant, currency=ngn, country=ng, amount=Decimal("4500.00"))
    assert resolve_price(variant, ng).amount == Decimal("4500.00")


@pytest.mark.django_db
def test_active_window_price_wins(variant):
    ngn = Currency.objects.get(code="NGN")
    ng = Country.objects.get(code="NG")
    now = timezone.now()
    Price.objects.create(variant=variant, currency=ngn, country=ng, amount=Decimal("4500.00"))
    Price.objects.create(
        variant=variant, currency=ngn, country=ng, amount=Decimal("3999.00"),
        starts_at=now - timezone.timedelta(days=1), ends_at=now + timezone.timedelta(days=1),
    )
    assert resolve_price(variant, ng).amount == Decimal("3999.00")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest apps/pricing/tests/test_resolve_price.py -v`
Expected: FAIL — the `pricing` app isn't installed, so `apps.pricing.models.Price` has no table / `RuntimeError: Model class ... isn't in an application in INSTALLED_APPS`.

- [ ] **Step 3: Register the pricing app**

In `backend/config/settings/base.py`, add `apps.pricing` to `INSTALLED_APPS` right after `apps.catalog`:

```python
    "apps.catalog",
    "apps.pricing",
```

- [ ] **Step 4: Create the migrations package + generate the migration**

Create `backend/apps/pricing/migrations/__init__.py` (empty).

Run: `uv run python manage.py makemigrations pricing`
Expected: creates `apps/pricing/migrations/0001_initial.py` with the `Price` model (FK to `catalog.ProductVariant`, `core.Currency`, `core.Country`, the `uniq_price_scope` constraint). It should list dependencies on `catalog` and `core`.

- [ ] **Step 5: Apply to dev DB + run tests**

Run: `uv run python manage.py migrate`
Expected: applies `pricing.0001_initial`.

Run: `uv run python -m pytest apps/pricing/tests/ -v`
Expected: PASS (the new 5 DB tests + the existing `test_resolved_price.py` dataclass test).

- [ ] **Step 6: Confirm system check + full suite**

Run: `uv run python manage.py check` → no issues.
Run: `uv run python -m pytest -q` → all green.

- [ ] **Step 7: Commit**

```bash
git add config/settings/base.py apps/pricing/migrations/__init__.py apps/pricing/migrations/0001_initial.py apps/pricing/tests/test_resolve_price.py
git commit -m "feat(pricing): activate app, migrate Price, add resolve_price DB tests"
```

---

## Task 6: Test factories

factory_boy factories the API plans (05b/05c) and future plans reuse. Kept in `apps/catalog/factories.py` (imported only by tests).

**Files:**
- Create: `backend/apps/catalog/factories.py`
- Test: `backend/apps/catalog/tests/test_factories.py`

- [ ] **Step 1: Write the failing test**

Create `backend/apps/catalog/tests/test_factories.py`:

```python
from decimal import Decimal

import pytest

from apps.catalog.factories import (
    BrandFactory,
    CategoryFactory,
    PriceFactory,
    ProductFactory,
    ProductVariantFactory,
)


@pytest.mark.django_db
def test_factories_build_valid_objects():
    brand = BrandFactory()
    assert brand.slug
    cat = CategoryFactory()
    assert cat.slug

    product = ProductFactory(brand=brand)
    product.categories.add(cat)
    assert product.slug
    assert product.status == "active"           # factory sets active by default

    variant = ProductVariantFactory(product=product)
    assert variant.sku
    assert variant.product == product


@pytest.mark.django_db
def test_price_factory_defaults_to_ngn():
    variant = ProductVariantFactory()
    price = PriceFactory(variant=variant)
    assert price.currency.code == "NGN"
    assert price.amount >= Decimal("0")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest apps/catalog/tests/test_factories.py -v`
Expected: FAIL — `ModuleNotFoundError: apps.catalog.factories`.

- [ ] **Step 3: Write the factories**

Create `backend/apps/catalog/factories.py`:

```python
"""factory_boy factories for catalog + pricing test data. Import only from tests."""
from decimal import Decimal

import factory

from apps.catalog.models import Brand, Category, Product, ProductVariant
from apps.core.models import Country, Currency
from apps.pricing.models import Price


class BrandFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Brand

    name = factory.Sequence(lambda n: f"Brand {n}")
    slug = factory.Sequence(lambda n: f"brand-{n}")


class CategoryFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Category

    name = factory.Sequence(lambda n: f"Category {n}")
    slug = factory.Sequence(lambda n: f"category-{n}")


class ProductFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Product

    name = factory.Sequence(lambda n: f"Product {n}")
    slug = factory.Sequence(lambda n: f"product-{n}")
    status = "active"


class ProductVariantFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ProductVariant

    product = factory.SubFactory(ProductFactory)
    sku = factory.Sequence(lambda n: f"SKU-{n}")
    name = factory.Sequence(lambda n: f"{n}ml")
    is_default = True


class PriceFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Price

    variant = factory.SubFactory(ProductVariantFactory)
    amount = Decimal("5000.00")
    country = None

    @factory.lazy_attribute
    def currency(self):
        # Seed migration guarantees NGN exists in every test DB.
        return Currency.objects.get(code="NGN")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest apps/catalog/tests/test_factories.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/catalog/factories.py apps/catalog/tests/test_factories.py
git commit -m "test(catalog): factory_boy factories for catalog + pricing"
```

---

## Task 7: Django admin registration (quick internal management)

Register catalog + pricing models in the low-level Django admin (`/django-admin/`, staff-only, IP-restricted in prod). This is NOT the customer-facing admin app (Plan-16+) — just gives Hammed a way to eyeball/edit data now.

**Files:**
- Create: `backend/apps/catalog/admin.py`

- [ ] **Step 1: Write the admin registration**

Create `backend/apps/catalog/admin.py`:

```python
from django.contrib import admin

from apps.catalog.models import (
    Brand,
    Category,
    Collection,
    Product,
    ProductImage,
    ProductVariant,
    ProductVideo,
    Tag,
)


class ProductVariantInline(admin.TabularInline):
    model = ProductVariant
    extra = 1


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 1


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "brand", "status", "is_featured")
    list_filter = ("status", "is_featured", "brand")
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}
    inlines = [ProductVariantInline, ProductImageInline]


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "parent", "is_active", "sort_order")
    prepopulated_fields = {"slug": ("name",)}


admin.site.register([Brand, Tag, Collection, ProductVideo])
```

- [ ] **Step 2: Verify it loads**

Run: `uv run python manage.py check`
Expected: no issues (admin registrations valid).

Run: `uv run python -m pytest -q`
Expected: all green (no test regressions).

- [ ] **Step 3: Commit**

```bash
git add apps/catalog/admin.py
git commit -m "feat(catalog): register catalog models in Django admin"
```

---

## Task 8: Docs — Plan-05a status

**Files:**
- Modify: `docs/architecture.md`

- [ ] **Step 1: Update status**

In `docs/architecture.md`, append to the **Current status** section:

```
Plan-05a (catalog foundation) ✅ — catalog models (Category/Brand/Tag/Collection, Product,
ProductVariant, ProductImage/Video), pricing app ACTIVATED (Price migrated, full resolve_price
DB tests green), factory_boy factories, Django-admin registration. Next: Plan-05b (public
country-aware read APIs).
```

- [ ] **Step 2: Commit**

```bash
git add docs/architecture.md
git commit -m "docs: record Plan-05a catalog foundation status"
```

---

## Final verification (stage)

- [ ] `uv run python -m pytest -q` — all green (Plan-04's 33 + catalog taxonomy/product/media/factories + pricing DB tests).
- [ ] `uv run python manage.py check` — no issues.
- [ ] `uv run python manage.py migrate` — clean (catalog 0001–0003 + pricing 0001 applied).
- [ ] Manual smoke: `uv run python manage.py shell -c "from apps.catalog.factories import ProductVariantFactory, PriceFactory; from apps.pricing.services import resolve_price; from apps.core.models import Country; v=ProductVariantFactory(); PriceFactory(variant=v); print(resolve_price(v, Country.objects.get(code='NG')))"` → prints a `ResolvedPrice(...)`.

**CHECKPOINT:** show Hammed the passing test list and a `resolve_price` result, confirming the pricing engine is live against real variants. (The two-country product JSON demo from the master guide's Plan-05 checkpoint happens at the end of Plan-05b, when the product API exists.)

---

## Self-review notes (author)

- **Spec coverage (Plan-05 item 1 — models):** Category/Brand/Tag/Collection (Task 2), Product + `available_countries` + specs/faqs JSON (Task 3), ProductVariant (Task 3), ProductImage/Video (Task 4). `get_ancestors()` helper on Category — Task 2. Collection `rule` choices — Task 2. ✅
- **Pricing activation:** the deferred Plan-04 migration + full `resolve_price` tests (country override, expired window, missing price, active window) — Task 5. ✅
- **Deliberately deferred to Plan-05b/05c (not this plan):** `sellable_in` helper, product list/detail/category/brand/collection read APIs, `request.country` price resolution in responses, Redis caching, N+1 query budget (05b); admin CRUD write APIs, image multipart upload, CSV import/export (05c). Rule-based Collection population (nightly Celery task) lands with the collections API in 05b. Flagged so nothing looks lost.
- **New dependency:** Pillow (Task 1) — required because `ImageField` won't pass system checks without it.
- **Types consistent:** `ResolvedPrice(amount, compare_at, currency, tax_rate, prices_include_tax)` is exercised by the new DB tests exactly as defined in `apps/pricing/services.py`. Factory names (`ProductVariantFactory`, `PriceFactory`, …) match between `factories.py` and its test.
