# Plan-05b — Catalog Public Read APIs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Public, country-aware read APIs for the storefront — product list (filters + ordering + sellability), product detail (variants priced per country, images, related), and taxonomy endpoints (categories tree, brands, collections) — with a Redis response cache and an N+1 query budget.

**Architecture:** New DRF read-only views in `apps.catalog` driven by `request.country` (set by the Plan-04 middleware). A single `sellable_in(product, country)` helper gates visibility everywhere ("available in country AND has a resolved price"). List price sort/filter uses a DB `Subquery` annotation of the product's minimum effective price in the country's currency; the exact per-variant price shown in detail comes from `resolve_price`. Responses are cached in Redis for 60s, keyed on `(path, querystring, country)`, invalidated by a version-bump signal on catalog/price writes.

**Tech Stack:** Django 5.2, DRF, django-filter (already installed), Django's built-in Redis cache backend, pytest. No new dependencies.

---

## Conventions for this plan (read once)

- **Run tests:** `uv run python -m pytest ...` from `backend/` (bare `pytest` is blocked).
- Read APIs are **public** (`AllowAny`) — the storefront calls them pre-login.
- `request.country` is always set (middleware defaults missing→NG, unknown→ZZ). Serializers read it from `self.context["request"].country`.
- Reuse Plan-05a factories (`apps.catalog.factories`) in tests.

## Cross-plan dependencies — deliberate stubs (flagged for Hammed)

These fields/filters depend on plans not yet built. This plan implements a **documented placeholder** and leaves a `# PLAN-0X` marker so nothing is silently missing:

- **Stock / `in_stock`** → Plan-06 (inventory). Serializers expose `in_stock` as `True` for now (a product with a price is considered orderable). The `in_stock` **filter** is accepted but a no-op until Plan-06. Marked `# PLAN-06`.
- **Full-text search `q`** → Plan-07 (Meilisearch). This plan does a plain DB `icontains` on name/short_description as a fallback. Marked `# PLAN-07`.
- **`best_selling` ordering** → Plan-10 (orders). Falls back to `newest` until order data exists. Marked `# PLAN-10`.

## Key design decision (flagged for Hammed) — price sort/filter

`resolve_price` has a 4-tier precedence + sale windows that can't be expressed as one ORM `ORDER BY`. For **list sorting and price_min/max filtering**, this plan annotates each product with `min_price` = the lowest active-window `Price.amount` for the country's currency where `country = <ctx>` OR `country IS NULL`. This is monotonic and correct for the common case; it does **not** replicate the strict country-over-null precedence purely for *sort order* (the exact displayed price still comes from `resolve_price`). If you want sort to honor full precedence, that's a heavier denormalization (a materialized `effective_price` column refreshed on price change) — say the word and it becomes its own task.

## File Structure

**Created:**
- `backend/apps/catalog/services.py` — `sellable_in`, `annotate_min_price`, cache helpers
- `backend/apps/catalog/api_serializers.py` — list/detail/taxonomy serializers
- `backend/apps/catalog/api_views.py` — read views
- `backend/apps/catalog/api_urls.py` — `/api/v1/` catalog routes
- `backend/apps/catalog/signals.py` — cache-version bump on writes
- `backend/apps/catalog/tests/test_sellable.py`, `test_product_api.py`, `test_taxonomy_api.py`, `test_cache.py`, `test_query_budget.py`

**Modified:**
- `backend/config/settings/base.py` — `CACHES`
- `backend/config/urls.py` — include catalog API routes
- `backend/apps/catalog/apps.py` — wire signals in `ready()`
- `docs/architecture.md` — Plan-05b status

---

## Task 1: `sellable_in` + price annotation service

**Files:**
- Create: `backend/apps/catalog/services.py`
- Test: `backend/apps/catalog/tests/test_sellable.py`

- [ ] **Step 1: Write the failing test**

Create `backend/apps/catalog/tests/test_sellable.py`:

```python
from decimal import Decimal

import pytest

from apps.catalog.factories import PriceFactory, ProductFactory, ProductVariantFactory
from apps.catalog.services import annotate_min_price, sellable_in
from apps.catalog.models import Product
from apps.core.models import Country


@pytest.mark.django_db
def test_sellable_requires_price():
    ng = Country.objects.get(code="NG")
    p = ProductFactory()
    v = ProductVariantFactory(product=p)
    assert sellable_in(p, ng) is False          # no price yet -> hidden
    PriceFactory(variant=v, amount=Decimal("1000"))
    assert sellable_in(p, ng) is True


@pytest.mark.django_db
def test_sellable_respects_available_countries():
    ng = Country.objects.get(code="NG")
    gb = Country.objects.get(code="GB")
    p = ProductFactory()
    v = ProductVariantFactory(product=p)
    PriceFactory(variant=v, amount=Decimal("1000"))   # NGN price
    p.available_countries.add(ng)                      # restricted to NG
    assert sellable_in(p, ng) is True
    assert sellable_in(p, gb) is False                 # not in available_countries


@pytest.mark.django_db
def test_annotate_min_price_filters_by_currency_context():
    ng = Country.objects.get(code="NG")
    p = ProductFactory()
    v = ProductVariantFactory(product=p)
    PriceFactory(variant=v, amount=Decimal("2500"))
    qs = annotate_min_price(Product.objects.all(), ng)
    got = qs.get(pk=p.pk)
    assert got.min_price == Decimal("2500")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest apps/catalog/tests/test_sellable.py -v`
Expected: FAIL — `ModuleNotFoundError: apps.catalog.services`.

- [ ] **Step 3: Write the service**

Create `backend/apps/catalog/services.py`:

```python
"""Catalog domain services: sellability + price annotation used by the read APIs."""
from __future__ import annotations

from django.db.models import OuterRef, Q, Subquery
from django.utils import timezone

from apps.pricing.services import resolve_price


def sellable_in(product, country) -> bool:
    """A product is visible/sellable in a country iff:
    (a) available_countries is empty OR contains the country, AND
    (b) at least one active variant resolves to a price in that country.
    ("hide until priced" — Hammed approved.)
    """
    allowed = product.available_countries.all()
    if allowed.exists() and country not in allowed:
        return False
    for variant in product.variants.filter(is_active=True):
        if resolve_price(variant, country) is not None:
            return True
    return False


def annotate_min_price(queryset, country):
    """Annotate each product with `min_price`: the lowest active-window Price
    amount for the country's currency where country matches OR is NULL.

    Used for price sort/filter in the list API. See the plan's design note —
    this is monotonic, not a full precedence replica; the displayed price comes
    from resolve_price. Products with no price get min_price=None.
    """
    from apps.pricing.models import Price

    now = timezone.now()
    active = (Q(starts_at__isnull=True) | Q(starts_at__lte=now)) & (
        Q(ends_at__isnull=True) | Q(ends_at__gte=now)
    )
    cheapest = (
        Price.objects.filter(
            active,
            variant__product=OuterRef("pk"),
            variant__is_active=True,
            currency=country.currency,
        )
        .filter(Q(country=country) | Q(country__isnull=True))
        .order_by("amount")
        .values("amount")[:1]
    )
    return queryset.annotate(min_price=Subquery(cheapest))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest apps/catalog/tests/test_sellable.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/catalog/services.py apps/catalog/tests/test_sellable.py
git commit -m "feat(catalog): sellable_in + min-price annotation services"
```

---

## Task 2: Read serializers

**Files:**
- Create: `backend/apps/catalog/api_serializers.py`
- Test: covered via the API tests in Tasks 3–5 (serializers aren't tested in isolation).

- [ ] **Step 1: Write the serializers**

Create `backend/apps/catalog/api_serializers.py`:

```python
from rest_framework import serializers

from apps.catalog.models import Brand, Category, Collection, Product, ProductVariant
from apps.core.serializers import CurrencySerializer
from apps.pricing.services import resolve_price


class BrandSerializer(serializers.ModelSerializer):
    class Meta:
        model = Brand
        fields = ["name", "slug", "logo", "description"]


class CategorySerializer(serializers.ModelSerializer):
    children = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = ["name", "slug", "image", "sort_order", "children"]

    def get_children(self, obj):
        kids = [c for c in obj.children.all() if c.is_active]
        return CategorySerializer(kids, many=True, context=self.context).data


class VariantSerializer(serializers.ModelSerializer):
    price = serializers.SerializerMethodField()
    in_stock = serializers.SerializerMethodField()

    class Meta:
        model = ProductVariant
        fields = ["sku", "name", "option_values", "price", "in_stock"]

    def get_price(self, obj):
        country = self.context["request"].country
        rp = resolve_price(obj, country)
        if rp is None:
            return None
        return {
            "amount": str(rp.amount),
            "compare_at": str(rp.compare_at) if rp.compare_at is not None else None,
            "currency": rp.currency,
            "tax_rate": str(rp.tax_rate),
            "prices_include_tax": rp.prices_include_tax,
        }

    def get_in_stock(self, obj):
        return True  # PLAN-06: real stock from inventory.available_qty > 0


class ProductListSerializer(serializers.ModelSerializer):
    from_price = serializers.SerializerMethodField()
    currency = serializers.SerializerMethodField()
    brand = serializers.SlugRelatedField(slug_field="slug", read_only=True)
    image = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = ["name", "slug", "brand", "is_featured", "from_price", "currency", "image"]

    def get_from_price(self, obj):
        amount = getattr(obj, "min_price", None)
        return str(amount) if amount is not None else None

    def get_currency(self, obj):
        return self.context["request"].country.currency.code

    def get_image(self, obj):
        first = obj.images.all()[:1]
        return first[0].image.url if first else None


class ProductDetailSerializer(serializers.ModelSerializer):
    brand = BrandSerializer(read_only=True)
    variants = serializers.SerializerMethodField()
    images = serializers.SerializerMethodField()
    related = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            "name", "slug", "brand", "description", "short_description",
            "ingredients", "directions", "warnings", "specs", "faqs",
            "seo_title", "seo_description", "variants", "images", "related",
        ]

    def get_variants(self, obj):
        active = obj.variants.filter(is_active=True)
        return VariantSerializer(active, many=True, context=self.context).data

    def get_images(self, obj):
        return [{"url": i.image.url, "alt": i.alt} for i in obj.images.all()]

    def get_related(self, obj):
        country = self.context["request"].country
        from apps.catalog.services import sellable_in

        rel = [p for p in obj.related.all() if sellable_in(p, country)]
        return ProductListSerializer(
            self.context["view"].annotate_qs(rel, country), many=True, context=self.context
        ).data


class CollectionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Collection
        fields = ["name", "slug", "description", "image"]
```

Note: `get_related` re-annotates a small list — see `annotate_qs` helper added on the view in Task 4. If that coupling feels awkward during execution, inline the annotation with `annotate_min_price` instead; both are fine.

- [ ] **Step 2: Commit (with Task 3 — serializers are exercised by the API tests)**

Serializers have no standalone test; they're committed alongside the list API in Task 3.

---

## Task 3: Product list API

`GET /api/v1/products/` — filters (category, brand, tag, collection, price_min/max, q, in_stock[stub]); ordering (newest, price_asc, price_desc, best_selling[→newest]); sellability exclusion; paginated (24/page).

**Files:**
- Create: `backend/apps/catalog/api_views.py`, `backend/apps/catalog/api_urls.py`
- Modify: `backend/config/urls.py`
- Test: `backend/apps/catalog/tests/test_product_api.py`

- [ ] **Step 1: Write the failing test**

Create `backend/apps/catalog/tests/test_product_api.py`:

```python
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.catalog.factories import (
    BrandFactory,
    CategoryFactory,
    PriceFactory,
    ProductFactory,
    ProductVariantFactory,
)
from apps.core.models import Country


def _priced_product(amount, **kwargs):
    p = ProductFactory(**kwargs)
    v = ProductVariantFactory(product=p)
    PriceFactory(variant=v, amount=Decimal(amount))
    return p


@pytest.mark.django_db
def test_list_hides_unpriced_products():
    _priced_product("1000")
    ProductFactory()  # no price -> hidden
    r = APIClient().get("/api/v1/products/")
    assert r.status_code == 200
    assert r.data["count"] == 1


@pytest.mark.django_db
def test_list_country_price_and_exclusion():
    ng = Country.objects.get(code="NG")
    p = _priced_product("1000")   # NGN only
    # In NG: visible with NGN from_price. In GB: no GBP price -> hidden.
    r_ng = APIClient().get("/api/v1/products/", HTTP_X_COUNTRY="NG")
    assert r_ng.data["count"] == 1
    row = r_ng.data["results"][0]
    assert row["from_price"] == "1000.00"
    assert row["currency"] == "NGN"

    r_gb = APIClient().get("/api/v1/products/", HTTP_X_COUNTRY="GB")
    assert r_gb.data["count"] == 0


@pytest.mark.django_db
def test_filter_by_brand_and_price_range():
    b = BrandFactory(slug="toke")
    _priced_product("1000", brand=b)
    _priced_product("5000", brand=b)
    _priced_product("9000")  # different brand (None)

    r = APIClient().get("/api/v1/products/?brand=toke&price_min=2000")
    assert {row["from_price"] for row in r.data["results"]} == {"5000.00"}


@pytest.mark.django_db
def test_ordering_price_asc():
    _priced_product("3000")
    _priced_product("1000")
    _priced_product("2000")
    r = APIClient().get("/api/v1/products/?ordering=price_asc")
    prices = [row["from_price"] for row in r.data["results"]]
    assert prices == ["1000.00", "2000.00", "3000.00"]


@pytest.mark.django_db
def test_filter_by_category():
    cat = CategoryFactory(slug="serums")
    p = _priced_product("1000")
    p.categories.add(cat)
    _priced_product("2000")
    r = APIClient().get("/api/v1/products/?category=serums")
    assert r.data["count"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest apps/catalog/tests/test_product_api.py -v`
Expected: FAIL — 404 (routes not wired).

- [ ] **Step 3: Write the list view**

Create `backend/apps/catalog/api_views.py`:

```python
from django.db.models import Q
from rest_framework import generics, permissions

from apps.catalog.api_serializers import ProductDetailSerializer, ProductListSerializer
from apps.catalog.models import Product
from apps.catalog.services import annotate_min_price

ORDERING = {
    "newest": "-published_at",
    "price_asc": "min_price",
    "price_desc": "-min_price",
    "best_selling": "-published_at",  # PLAN-10: real best-selling from order data
}


class ProductListView(generics.ListAPIView):
    serializer_class = ProductListSerializer
    permission_classes = [permissions.AllowAny]

    def annotate_qs(self, products, country):
        pks = [p.pk for p in products]
        return annotate_min_price(Product.objects.filter(pk__in=pks), country)

    def get_queryset(self):
        country = self.request.country
        qs = (
            Product.objects.filter(status="active")
            .prefetch_related("images")
            .select_related("brand")
        )
        # Restrict to products available in this country (empty available_countries = all).
        qs = qs.filter(Q(available_countries__isnull=True) | Q(available_countries=country)).distinct()
        qs = annotate_min_price(qs, country)
        # "hide until priced": drop rows with no resolvable price in this currency.
        qs = qs.filter(min_price__isnull=False)

        p = self.request.query_params
        if p.get("category"):
            qs = qs.filter(categories__slug=p["category"])
        if p.get("brand"):
            qs = qs.filter(brand__slug=p["brand"])
        if p.get("tag"):
            qs = qs.filter(tags__slug=p["tag"])
        if p.get("collection"):
            qs = qs.filter(collections__slug=p["collection"])
        if p.get("price_min"):
            qs = qs.filter(min_price__gte=p["price_min"])
        if p.get("price_max"):
            qs = qs.filter(min_price__lte=p["price_max"])
        if p.get("q"):  # PLAN-07: replace with Meilisearch
            term = p["q"]
            qs = qs.filter(Q(name__icontains=term) | Q(short_description__icontains=term))
        # in_stock filter is a no-op until PLAN-06 inventory exists.

        ordering = ORDERING.get(p.get("ordering", "newest"), "-published_at")
        return qs.order_by(ordering, "name").distinct()


class ProductDetailView(generics.RetrieveAPIView):
    serializer_class = ProductDetailSerializer
    permission_classes = [permissions.AllowAny]
    lookup_field = "slug"

    def annotate_qs(self, products, country):
        pks = [p.pk for p in products]
        return annotate_min_price(Product.objects.filter(pk__in=pks), country)

    def get_queryset(self):
        return Product.objects.filter(status="active").select_related("brand").prefetch_related(
            "images", "variants", "related__images"
        )

    def get_object(self):
        from django.http import Http404

        from apps.catalog.services import sellable_in

        obj = super().get_object()
        if not sellable_in(obj, self.request.country):
            raise Http404("Not available in this country.")
        return obj
```

Create `backend/apps/catalog/api_urls.py`:

```python
from django.urls import path

from apps.catalog.api_views import ProductDetailView, ProductListView

urlpatterns = [
    path("products/", ProductListView.as_view(), name="product-list"),
    path("products/<slug:slug>/", ProductDetailView.as_view(), name="product-detail"),
]
```

In `backend/config/urls.py`, add under the API v1 block:

```python
    path("api/v1/meta/", include("apps.core.urls")),
    path("api/v1/", include("apps.catalog.api_urls")),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest apps/catalog/tests/test_product_api.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/catalog/api_serializers.py apps/catalog/api_views.py apps/catalog/api_urls.py config/urls.py apps/catalog/tests/test_product_api.py
git commit -m "feat(catalog): country-aware product list API (filters, ordering, sellability)"
```

---

## Task 4: Product detail API

Covered by `ProductDetailView` written in Task 3. This task adds its tests.

**Files:**
- Test: append to `backend/apps/catalog/tests/test_product_api.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/apps/catalog/tests/test_product_api.py`:

```python
@pytest.mark.django_db
def test_detail_shows_variant_prices_per_country():
    p = _priced_product("1000")
    r = APIClient().get(f"/api/v1/products/{p.slug}/", HTTP_X_COUNTRY="NG")
    assert r.status_code == 200
    assert r.data["slug"] == p.slug
    assert len(r.data["variants"]) == 1
    price = r.data["variants"][0]["price"]
    assert price["amount"] == "1000.00"
    assert price["currency"] == "NGN"
    assert price["tax_rate"] == "7.50"


@pytest.mark.django_db
def test_detail_404_when_not_sellable_in_country():
    p = _priced_product("1000")  # NGN only
    r = APIClient().get(f"/api/v1/products/{p.slug}/", HTTP_X_COUNTRY="GB")
    assert r.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails/passes**

Run: `uv run python -m pytest apps/catalog/tests/test_product_api.py -k detail -v`
Expected: PASS (the detail view already exists from Task 3; if a test fails, fix the view/serializer, not the test).

- [ ] **Step 3: Commit**

```bash
git add apps/catalog/tests/test_product_api.py
git commit -m "test(catalog): product detail API — per-country variant prices + 404"
```

---

## Task 5: Taxonomy endpoints (categories tree, brands, collections)

`GET /api/v1/categories/` (active tree), `GET /api/v1/brands/`, `GET /api/v1/collections/{slug}/`.

**Files:**
- Modify: `backend/apps/catalog/api_views.py`, `backend/apps/catalog/api_urls.py`
- Test: `backend/apps/catalog/tests/test_taxonomy_api.py`

- [ ] **Step 1: Write the failing test**

Create `backend/apps/catalog/tests/test_taxonomy_api.py`:

```python
import pytest
from rest_framework.test import APIClient

from apps.catalog.factories import BrandFactory, CategoryFactory
from apps.catalog.models import Collection


@pytest.mark.django_db
def test_categories_tree():
    root = CategoryFactory(slug="skincare", name="Skincare")
    CategoryFactory(slug="face", name="Face", parent=root)
    r = APIClient().get("/api/v1/categories/")
    assert r.status_code == 200
    top = [c for c in r.data if c["slug"] == "skincare"][0]
    assert [k["slug"] for k in top["children"]] == ["face"]


@pytest.mark.django_db
def test_brands_list():
    BrandFactory(slug="toke", name="Toke")
    r = APIClient().get("/api/v1/brands/")
    assert {b["slug"] for b in r.data} == {"toke"}


@pytest.mark.django_db
def test_collection_detail():
    Collection.objects.create(name="New Arrivals", slug="new-arrivals")
    r = APIClient().get("/api/v1/collections/new-arrivals/")
    assert r.status_code == 200
    assert r.data["slug"] == "new-arrivals"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest apps/catalog/tests/test_taxonomy_api.py -v`
Expected: FAIL — 404.

- [ ] **Step 3: Add the views**

Append to `backend/apps/catalog/api_views.py`:

```python
from apps.catalog.api_serializers import (
    BrandSerializer,
    CategorySerializer,
    CollectionSerializer,
)
from apps.catalog.models import Brand, Category, Collection


class CategoryTreeView(generics.ListAPIView):
    serializer_class = CategorySerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = None

    def get_queryset(self):
        # Return roots only; children are nested by the serializer.
        return (
            Category.objects.filter(is_active=True, parent__isnull=True)
            .prefetch_related("children")
            .order_by("sort_order", "name")
        )


class BrandListView(generics.ListAPIView):
    serializer_class = BrandSerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = None
    queryset = Brand.objects.filter(is_active=True).order_by("name")


class CollectionDetailView(generics.RetrieveAPIView):
    serializer_class = CollectionSerializer
    permission_classes = [permissions.AllowAny]
    lookup_field = "slug"
    queryset = Collection.objects.filter(is_active=True)
```

Append to `backend/apps/catalog/api_urls.py` `urlpatterns`:

```python
    path("categories/", CategoryTreeView.as_view(), name="category-tree"),
    path("brands/", BrandListView.as_view(), name="brand-list"),
    path("collections/<slug:slug>/", CollectionDetailView.as_view(), name="collection-detail"),
```

(and add `CategoryTreeView, BrandListView, CollectionDetailView` to the import in `api_urls.py`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest apps/catalog/tests/test_taxonomy_api.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/catalog/api_views.py apps/catalog/api_urls.py apps/catalog/tests/test_taxonomy_api.py
git commit -m "feat(catalog): categories tree, brands, collection detail APIs"
```

---

## Task 6: Redis response cache + invalidation

Cache list/detail responses 60s, keyed on `(path, querystring, country)` under a namespace version that bumps on any catalog/price write.

**Files:**
- Modify: `backend/config/settings/base.py` (CACHES)
- Modify: `backend/apps/catalog/services.py` (cache key + version helpers)
- Modify: `backend/apps/catalog/api_views.py` (use cache in list/retrieve)
- Create: `backend/apps/catalog/signals.py`
- Modify: `backend/apps/catalog/apps.py` (`ready()`)
- Test: `backend/apps/catalog/tests/test_cache.py`

- [ ] **Step 1: Add CACHES**

In `backend/config/settings/base.py`, after the `REDIS_URL` line, add:

```python
CACHES = {
    "default": {
        # Dev/tests default to locmem (hermetic). Prod sets these to Redis via env.
        "BACKEND": env("CACHE_BACKEND", default="django.core.cache.backends.locmem.LocMemCache"),
        "LOCATION": env("CACHE_LOCATION", default="toke-cache"),
    }
}
```

(In prod `.env`: `CACHE_BACKEND=django.core.cache.backends.redis.RedisCache` and `CACHE_LOCATION=${REDIS_URL}`.)

- [ ] **Step 2: Write the failing test**

Create `backend/apps/catalog/tests/test_cache.py`:

```python
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.catalog.factories import PriceFactory, ProductFactory, ProductVariantFactory


@pytest.mark.django_db
def test_list_cache_invalidates_on_new_product(settings):
    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "t"}}
    from django.core.cache import cache

    cache.clear()
    p = ProductFactory()
    PriceFactory(variant=ProductVariantFactory(product=p), amount=Decimal("1000"))

    c = APIClient()
    assert c.get("/api/v1/products/").data["count"] == 1
    # Add another priced product -> the post_save signal must bust the cached list.
    p2 = ProductFactory()
    PriceFactory(variant=ProductVariantFactory(product=p2), amount=Decimal("2000"))
    assert c.get("/api/v1/products/").data["count"] == 2
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run python -m pytest apps/catalog/tests/test_cache.py -v`
Expected: FAIL — the second call returns a stale `count == 1` (no invalidation yet).

- [ ] **Step 4: Add cache helpers**

Append to `backend/apps/catalog/services.py`:

```python
from django.core.cache import cache

_CACHE_VERSION_KEY = "catalog:cache_version"
CATALOG_CACHE_TTL = 60  # seconds


def catalog_cache_version() -> int:
    return cache.get_or_set(_CACHE_VERSION_KEY, 1, None)


def bump_catalog_cache() -> None:
    try:
        cache.incr(_CACHE_VERSION_KEY)
    except ValueError:
        cache.set(_CACHE_VERSION_KEY, 1, None)


def catalog_cache_key(request) -> str:
    country = request.country.code
    qs = request.META.get("QUERY_STRING", "")
    return f"catalog:{catalog_cache_version()}:{country}:{request.path}?{qs}"
```

- [ ] **Step 5: Use the cache in the views**

In `backend/apps/catalog/api_views.py`, add a small mixin and apply to both list & detail views:

```python
from rest_framework.response import Response

from apps.catalog.services import CATALOG_CACHE_TTL, catalog_cache_key
from django.core.cache import cache as _cache


class CatalogCacheMixin:
    def _cached_response(self, request, produce):
        key = catalog_cache_key(request)
        data = _cache.get(key)
        if data is None:
            data = produce().data
            _cache.set(key, data, CATALOG_CACHE_TTL)
        return Response(data)

    def list(self, request, *args, **kwargs):
        return self._cached_response(request, lambda: super(CatalogCacheMixin, self).list(request, *args, **kwargs))

    def retrieve(self, request, *args, **kwargs):
        return self._cached_response(request, lambda: super(CatalogCacheMixin, self).retrieve(request, *args, **kwargs))
```

Add `CatalogCacheMixin` as the first base of `ProductListView`, `ProductDetailView`, `CategoryTreeView`, `BrandListView`, `CollectionDetailView` (e.g. `class ProductListView(CatalogCacheMixin, generics.ListAPIView):`).

- [ ] **Step 6: Add the invalidation signal**

Create `backend/apps/catalog/signals.py`:

```python
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from apps.catalog.models import Brand, Category, Collection, Product, ProductImage, ProductVariant
from apps.catalog.services import bump_catalog_cache
from apps.pricing.models import Price

_WATCHED = [Product, ProductVariant, ProductImage, Category, Brand, Collection, Price]


@receiver(post_save)
@receiver(post_delete)
def _invalidate_catalog_cache(sender, **kwargs):
    if sender in _WATCHED:
        bump_catalog_cache()
```

Wire it in `backend/apps/catalog/apps.py`:

```python
    def ready(self):
        from apps.catalog import signals  # noqa: F401
```

- [ ] **Step 7: Run test to verify it passes**

Run: `uv run python -m pytest apps/catalog/tests/test_cache.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add config/settings/base.py apps/catalog/services.py apps/catalog/api_views.py apps/catalog/signals.py apps/catalog/apps.py apps/catalog/tests/test_cache.py
git commit -m "feat(catalog): 60s Redis response cache with version-bump invalidation"
```

---

## Task 7: N+1 query budget

Guard the list endpoint against query blow-up as the page grows.

**Files:**
- Test: `backend/apps/catalog/tests/test_query_budget.py`

- [ ] **Step 1: Write the test**

Create `backend/apps/catalog/tests/test_query_budget.py`:

```python
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.catalog.factories import PriceFactory, ProductFactory, ProductVariantFactory


@pytest.mark.django_db
def test_product_list_query_budget(django_assert_max_num_queries, settings):
    # Fresh locmem cache so we measure the DB path, not a cache hit.
    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "q"}}
    from django.core.cache import cache

    cache.clear()
    for i in range(24):
        p = ProductFactory()
        PriceFactory(variant=ProductVariantFactory(product=p), amount=Decimal("1000"))

    c = APIClient()
    with django_assert_max_num_queries(12):
        r = c.get("/api/v1/products/")
    assert r.data["count"] == 24
```

Note: budget is 12 (list qs + count + pagination + prefetch images/brand + min_price subquery + cache-version). If it exceeds, add `prefetch_related`/`select_related` — do NOT loosen the number without cause. The master guide's target is "≤ 8 for the core query"; 12 leaves headroom for the cache-version read and pagination count.

- [ ] **Step 2: Run test**

Run: `uv run python -m pytest apps/catalog/tests/test_query_budget.py -v`
Expected: PASS. If it fails on query count, inspect with `--pdb` or add the missing prefetch; the `from_price` comes from the annotation (no per-row price query) and `image` from the prefetched `images`.

- [ ] **Step 3: Commit**

```bash
git add apps/catalog/tests/test_query_budget.py
git commit -m "test(catalog): N+1 query budget for product list"
```

---

## Task 8: Docs + final verification

**Files:**
- Modify: `docs/architecture.md`

- [ ] **Step 1: Update status**

In `docs/architecture.md`, append to **Current status**:

```
Plan-05b (catalog read APIs) ✅ — public country-aware product list (filters/ordering/sellability),
product detail (per-country variant prices), categories tree / brands / collections, 60s Redis
response cache with version-bump invalidation, N+1 budget. Stubs pending later plans: stock/in_stock
(Plan-06), full-text search (Plan-07), best_selling order (Plan-10). Next: Plan-05c (admin write + CSV).
```

- [ ] **Step 2: Commit**

```bash
git add docs/architecture.md
git commit -m "docs: record Plan-05b catalog read APIs status"
```

---

## Final verification (stage)

- [ ] `uv run python -m pytest -q` — all green.
- [ ] `uv run python manage.py check` — no issues.
- [ ] **Manual two-country smoke** (the master guide's Plan-05 checkpoint): create a product with a variant priced in NGN and GBP, then:
  - `curl -s http://127.0.0.1:8000/api/v1/products/<slug>/ -H "X-Country: NG"` → NGN price
  - `curl -s http://127.0.0.1:8000/api/v1/products/<slug>/ -H "X-Country: GB"` → GBP price
  Confirm currency/amount differ per country.

**CHECKPOINT:** show Hammed the same product JSON in NG vs GB (different currency + price), and the passing test list.

---

## Self-review notes (author)

- **Spec coverage (Plan-05 item 2 — read APIs):** product list with all named filters (category/brand/tag/collection/price_min/max/q) + orderings (newest/price_asc/price_desc/best_selling) — Task 3; `sellable_in` gating "hide until priced" — Task 1 + used in list/detail; product detail with per-variant `resolve_price`, images, related — Tasks 3–4; categories tree / brands / collections — Task 5; Redis 60s cache keyed (path, querystring, country) + signal invalidation — Task 6; N+1 budget test — Task 7. ✅
- **Flagged stubs (need later plans):** `in_stock`/stock (Plan-06), full-text `q` (Plan-07 — DB icontains for now), `best_selling` (Plan-10 — → newest). Each marked in code with `# PLAN-0X`.
- **Flagged design decision:** price sort/filter uses a monotonic `min_price` annotation, not a full `resolve_price` precedence replica; exact displayed prices use `resolve_price`. Escalation path (materialized `effective_price`) noted if strict sort precedence is required.
- **Deferred to Plan-05c (not here):** all admin write/CRUD, image multipart upload, CSV import/export, and the nightly rule-based Collection population task.
- **Types consistent:** the variant `price` dict mirrors `ResolvedPrice` fields; `min_price` annotation is read by both the list serializer's `from_price` and the ordering/filtering.
```
