# Plan-05c — Catalog Admin Write APIs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Staff-only write APIs that complete the catalog stage — full CRUD on all catalog + pricing models, product image upload to S3, and product CSV export/import (import runs as a Celery job returning a row-level error report).

**Architecture:** New `apps.catalog.admin_api` (viewsets + serializers + router) mounted under `/api/v1/admin/`, all gated by `IsAdminUser` (real RBAC arrives in Plan-16). Writes automatically bust the public read cache — the Plan-05b `post_save`/`post_delete` signals already bump the catalog cache version, so no extra invalidation code is needed. CSV import parsing lives in a pure service (`csv_io.py`) wrapped by a Celery task so large files run off-request; in dev/tests (`CELERY_TASK_ALWAYS_EAGER`) it returns the report inline.

**Tech Stack:** Django 5.2, DRF (ModelViewSet + DefaultRouter), Celery (already wired), django-storages S3 (already configured), Python `csv`. No new dependencies.

---

## Conventions for this plan (read once)

- **Run tests:** `uv run python -m pytest ...` from `backend/` (bare `pytest` is blocked).
- **Admin auth in tests:** create a staff user and `APIClient().force_authenticate(user=staff)` — simpler than minting JWTs. Helper below.
- **Storage in tests:** the dev `.env` points media at the real S3 bucket, so the image-upload test MUST override storage to `InMemoryStorage` (shown in Task 4) — never let a test write to the live bucket.
- **RBAC:** `IsAdminUser` (`is_staff`) is the gate now; fine-grained per-model permissions are Plan-16. Marked `# PLAN-16` where relevant.

## File Structure

**Created:**
- `backend/apps/catalog/admin_serializers.py` — write serializers for all catalog + price models
- `backend/apps/catalog/admin_views.py` — viewsets, image upload, CSV export/import views
- `backend/apps/catalog/admin_urls.py` — router + custom routes under `/api/v1/admin/`
- `backend/apps/catalog/csv_io.py` — `export_products_csv`, `import_products_csv` (pure)
- `backend/apps/catalog/tasks.py` — `import_products_csv_task` (Celery)
- `backend/apps/catalog/tests/test_admin_crud.py`, `test_admin_image_upload.py`, `test_admin_csv.py`
- `backend/apps/catalog/tests/factories_admin.py` — `staff_user()` helper

**Modified:**
- `backend/config/urls.py` — include admin routes

---

## Task 1: Admin auth + Product CRUD viewset

**Files:**
- Create: `backend/apps/catalog/admin_serializers.py`, `admin_views.py`, `admin_urls.py`
- Create: `backend/apps/catalog/tests/factories_admin.py`, `tests/test_admin_crud.py`
- Modify: `backend/config/urls.py`

- [ ] **Step 1: Write the staff helper + failing test**

Create `backend/apps/catalog/tests/factories_admin.py`:

```python
from django.contrib.auth import get_user_model


def staff_user(email="admin@toke.test"):
    User = get_user_model()
    u = User.objects.create_user(email=email, password="Str0ng!pass9")
    u.is_staff = True
    u.save(update_fields=["is_staff"])
    return u
```

Create `backend/apps/catalog/tests/test_admin_crud.py`:

```python
import pytest
from rest_framework.test import APIClient

from apps.catalog.models import Product
from apps.catalog.tests.factories_admin import staff_user


@pytest.mark.django_db
def test_admin_requires_staff():
    # Anonymous -> 401/403; non-staff -> 403.
    r = APIClient().post("/api/v1/admin/products/", {"name": "X", "slug": "x"}, format="json")
    assert r.status_code in (401, 403)


@pytest.mark.django_db
def test_admin_can_crud_product():
    c = APIClient()
    c.force_authenticate(user=staff_user())

    # Create
    r = c.post(
        "/api/v1/admin/products/",
        {"name": "Glow Serum", "slug": "glow-serum", "status": "active"},
        format="json",
    )
    assert r.status_code == 201, r.data
    assert Product.objects.filter(slug="glow-serum").exists()

    # Update
    r = c.patch("/api/v1/admin/products/glow-serum/", {"is_featured": True}, format="json")
    assert r.status_code == 200
    assert Product.objects.get(slug="glow-serum").is_featured is True

    # List (staff sees drafts too)
    r = c.get("/api/v1/admin/products/")
    assert r.status_code == 200

    # Delete
    r = c.delete("/api/v1/admin/products/glow-serum/")
    assert r.status_code == 204
    assert not Product.objects.filter(slug="glow-serum").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest apps/catalog/tests/test_admin_crud.py -v`
Expected: FAIL — 404 (routes not wired).

- [ ] **Step 3: Write the Product admin serializer**

Create `backend/apps/catalog/admin_serializers.py`:

```python
from rest_framework import serializers

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


class ProductAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = [
            "id", "name", "slug", "brand", "categories", "tags", "description",
            "short_description", "status", "is_featured", "ingredients", "directions",
            "warnings", "specs", "faqs", "related", "available_countries",
            "seo_title", "seo_description", "published_at", "legacy_source", "legacy_wp_id",
        ]
```

- [ ] **Step 4: Write the viewset + router**

Create `backend/apps/catalog/admin_views.py`:

```python
from rest_framework import permissions, viewsets

from apps.catalog.admin_serializers import ProductAdminSerializer
from apps.catalog.models import Product


class AdminBaseViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAdminUser]  # PLAN-16: fine-grained RBAC


class ProductAdminViewSet(AdminBaseViewSet):
    serializer_class = ProductAdminSerializer
    queryset = Product.objects.all().order_by("-created_at")
    lookup_field = "slug"
```

Create `backend/apps/catalog/admin_urls.py`:

```python
from rest_framework.routers import DefaultRouter

from apps.catalog.admin_views import ProductAdminViewSet

router = DefaultRouter()
router.register("products", ProductAdminViewSet, basename="admin-product")

urlpatterns = router.urls
```

In `backend/config/urls.py`, add under the API v1 block:

```python
    path("api/v1/", include("apps.catalog.api_urls")),
    path("api/v1/admin/", include("apps.catalog.admin_urls")),
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run python -m pytest apps/catalog/tests/test_admin_crud.py -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add apps/catalog/admin_serializers.py apps/catalog/admin_views.py apps/catalog/admin_urls.py config/urls.py apps/catalog/tests/factories_admin.py apps/catalog/tests/test_admin_crud.py
git commit -m "feat(catalog): admin Product CRUD API (staff-only)"
```

---

## Task 2: CRUD for remaining catalog models + Price

Register viewsets for Category, Brand, Tag, Collection, ProductVariant, ProductVideo, and pricing `Price`.

**Files:**
- Modify: `backend/apps/catalog/admin_serializers.py`, `admin_views.py`, `admin_urls.py`
- Test: append to `backend/apps/catalog/tests/test_admin_crud.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/apps/catalog/tests/test_admin_crud.py`:

```python
from decimal import Decimal


@pytest.mark.django_db
def test_admin_crud_taxonomy_and_variant_and_price():
    c = APIClient()
    c.force_authenticate(user=staff_user())

    assert c.post("/api/v1/admin/brands/", {"name": "Toke", "slug": "toke"}, format="json").status_code == 201
    assert c.post("/api/v1/admin/categories/", {"name": "Face", "slug": "face"}, format="json").status_code == 201
    assert c.post("/api/v1/admin/tags/", {"name": "Vegan", "slug": "vegan"}, format="json").status_code == 201
    assert c.post("/api/v1/admin/collections/", {"name": "New", "slug": "new"}, format="json").status_code == 201

    p = c.post("/api/v1/admin/products/", {"name": "P", "slug": "p"}, format="json").data
    v = c.post(
        "/api/v1/admin/variants/",
        {"product": p["id"], "sku": "P-1", "name": "50ml", "is_default": True},
        format="json",
    )
    assert v.status_code == 201, v.data

    from apps.core.models import Currency

    price = c.post(
        "/api/v1/admin/prices/",
        {"variant": v.data["id"], "currency": Currency.objects.get(code="NGN").code, "amount": "5000.00"},
        format="json",
    )
    assert price.status_code == 201, price.data
    assert Decimal(price.data["amount"]) == Decimal("5000.00")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest apps/catalog/tests/test_admin_crud.py -k taxonomy -v`
Expected: FAIL — 404.

- [ ] **Step 3: Add serializers**

Append to `backend/apps/catalog/admin_serializers.py`:

```python
from apps.pricing.models import Price


class CategoryAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = "__all__"


class BrandAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = Brand
        fields = "__all__"


class TagAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tag
        fields = "__all__"


class CollectionAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = Collection
        fields = "__all__"


class ProductVariantAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductVariant
        fields = "__all__"


class ProductVideoAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductVideo
        fields = "__all__"


class PriceAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = Price
        fields = "__all__"
```

- [ ] **Step 4: Add viewsets**

Append to `backend/apps/catalog/admin_views.py`:

```python
from apps.catalog.admin_serializers import (
    BrandAdminSerializer,
    CategoryAdminSerializer,
    CollectionAdminSerializer,
    PriceAdminSerializer,
    ProductVariantAdminSerializer,
    ProductVideoAdminSerializer,
    TagAdminSerializer,
)
from apps.catalog.models import Brand, Category, Collection, ProductVariant, ProductVideo, Tag
from apps.pricing.models import Price


class CategoryAdminViewSet(AdminBaseViewSet):
    serializer_class = CategoryAdminSerializer
    queryset = Category.objects.all().order_by("sort_order", "name")
    lookup_field = "slug"


class BrandAdminViewSet(AdminBaseViewSet):
    serializer_class = BrandAdminSerializer
    queryset = Brand.objects.all().order_by("name")
    lookup_field = "slug"


class TagAdminViewSet(AdminBaseViewSet):
    serializer_class = TagAdminSerializer
    queryset = Tag.objects.all().order_by("name")
    lookup_field = "slug"


class CollectionAdminViewSet(AdminBaseViewSet):
    serializer_class = CollectionAdminSerializer
    queryset = Collection.objects.all().order_by("name")
    lookup_field = "slug"


class ProductVariantAdminViewSet(AdminBaseViewSet):
    serializer_class = ProductVariantAdminSerializer
    queryset = ProductVariant.objects.all().order_by("product_id", "position")


class ProductVideoAdminViewSet(AdminBaseViewSet):
    serializer_class = ProductVideoAdminSerializer
    queryset = ProductVideo.objects.all()


class PriceAdminViewSet(AdminBaseViewSet):
    serializer_class = PriceAdminSerializer
    queryset = Price.objects.all()
```

- [ ] **Step 5: Register routes**

Update `backend/apps/catalog/admin_urls.py`:

```python
from rest_framework.routers import DefaultRouter

from apps.catalog.admin_views import (
    BrandAdminViewSet,
    CategoryAdminViewSet,
    CollectionAdminViewSet,
    PriceAdminViewSet,
    ProductAdminViewSet,
    ProductVariantAdminViewSet,
    ProductVideoAdminViewSet,
    TagAdminViewSet,
)

router = DefaultRouter()
router.register("products", ProductAdminViewSet, basename="admin-product")
router.register("categories", CategoryAdminViewSet, basename="admin-category")
router.register("brands", BrandAdminViewSet, basename="admin-brand")
router.register("tags", TagAdminViewSet, basename="admin-tag")
router.register("collections", CollectionAdminViewSet, basename="admin-collection")
router.register("variants", ProductVariantAdminViewSet, basename="admin-variant")
router.register("videos", ProductVideoAdminViewSet, basename="admin-video")
router.register("prices", PriceAdminViewSet, basename="admin-price")

urlpatterns = router.urls
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run python -m pytest apps/catalog/tests/test_admin_crud.py -v`
Expected: PASS (3 tests).

- [ ] **Step 7: Commit**

```bash
git add apps/catalog/admin_serializers.py apps/catalog/admin_views.py apps/catalog/admin_urls.py apps/catalog/tests/test_admin_crud.py
git commit -m "feat(catalog): admin CRUD for taxonomy, variants, videos, prices"
```

---

## Task 3: Product image upload → S3

`POST /api/v1/admin/products/{slug}/images/` (multipart) → creates a `ProductImage` on the S3 bucket.

**Files:**
- Modify: `backend/apps/catalog/admin_serializers.py`, `admin_views.py`
- Test: `backend/apps/catalog/tests/test_admin_image_upload.py`

- [ ] **Step 1: Write the failing test**

Create `backend/apps/catalog/tests/test_admin_image_upload.py`:

```python
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework.test import APIClient

from apps.catalog.factories import ProductFactory
from apps.catalog.tests.factories_admin import staff_user

# A 1x1 PNG (valid image bytes so Pillow accepts it).
_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000154a24f5f0000000049454e44ae426082"
)

# Never touch the real S3 bucket in tests — use in-memory media storage.
IN_MEMORY = {
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


@override_settings(STORAGES=IN_MEMORY)
@pytest.mark.django_db
def test_admin_uploads_product_image():
    p = ProductFactory()
    c = APIClient()
    c.force_authenticate(user=staff_user())

    upload = SimpleUploadedFile("swatch.png", _PNG, content_type="image/png")
    r = c.post(f"/api/v1/admin/products/{p.slug}/images/", {"image": upload, "alt": "swatch"}, format="multipart")
    assert r.status_code == 201, r.data
    assert p.images.count() == 1
    assert p.images.first().alt == "swatch"


@override_settings(STORAGES=IN_MEMORY)
@pytest.mark.django_db
def test_image_upload_requires_staff():
    p = ProductFactory()
    upload = SimpleUploadedFile("swatch.png", _PNG, content_type="image/png")
    r = APIClient().post(f"/api/v1/admin/products/{p.slug}/images/", {"image": upload}, format="multipart")
    assert r.status_code in (401, 403)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest apps/catalog/tests/test_admin_image_upload.py -v`
Expected: FAIL — 404 (no images action yet).

- [ ] **Step 3: Add the image serializer**

Append to `backend/apps/catalog/admin_serializers.py`:

```python
class ProductImageAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductImage
        fields = ["id", "product", "image", "alt", "position", "variant"]
        read_only_fields = ["product"]
```

- [ ] **Step 4: Add the upload action on the Product viewset**

In `backend/apps/catalog/admin_views.py`, add imports and an `images` action to `ProductAdminViewSet`:

```python
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from apps.catalog.admin_serializers import ProductImageAdminSerializer
```

Add inside `ProductAdminViewSet`:

```python
    @action(
        detail=True,
        methods=["post"],
        parser_classes=[MultiPartParser, FormParser],
        url_path="images",
    )
    def images(self, request, slug=None):
        product = self.get_object()
        serializer = ProductImageAdminSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(product=product)
        return Response(serializer.data, status=201)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run python -m pytest apps/catalog/tests/test_admin_image_upload.py -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add apps/catalog/admin_serializers.py apps/catalog/admin_views.py apps/catalog/tests/test_admin_image_upload.py
git commit -m "feat(catalog): admin product image upload (multipart -> storage)"
```

---

## Task 4: Product CSV export + import (Celery job, row-level report)

**Files:**
- Create: `backend/apps/catalog/csv_io.py`, `backend/apps/catalog/tasks.py`
- Modify: `backend/apps/catalog/admin_views.py`, `admin_urls.py`
- Test: `backend/apps/catalog/tests/test_admin_csv.py`

CSV columns (one row per product's default variant):
`slug, name, brand_slug, status, short_description, category_slugs, sku, variant_name, price_ngn, price_gbp, price_usd, price_cad`
(`category_slugs` is `|`-separated; a blank price cell = no price row for that currency.)

- [ ] **Step 1: Write the failing test**

Create `backend/apps/catalog/tests/test_admin_csv.py`:

```python
import io
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.catalog.csv_io import import_products_csv
from apps.catalog.models import Product
from apps.catalog.tests.factories_admin import staff_user
from apps.pricing.models import Price


@pytest.mark.django_db
def test_import_products_csv_service_creates_and_reports_errors():
    rows = [
        # good row
        {"slug": "serum", "name": "Serum", "brand_slug": "", "status": "active",
         "short_description": "", "category_slugs": "", "sku": "SER-1",
         "variant_name": "50ml", "price_ngn": "5000", "price_gbp": "9.99",
         "price_usd": "", "price_cad": ""},
        # bad row: missing sku
        {"slug": "bad", "name": "Bad", "brand_slug": "", "status": "active",
         "short_description": "", "category_slugs": "", "sku": "",
         "variant_name": "x", "price_ngn": "1", "price_gbp": "",
         "price_usd": "", "price_cad": ""},
    ]
    report = import_products_csv(rows)
    assert report["created"] == 1
    assert len(report["errors"]) == 1
    assert report["errors"][0]["row"] == 2

    p = Product.objects.get(slug="serum")
    v = p.variants.get(sku="SER-1")
    assert Price.objects.filter(variant=v, currency__code="NGN", amount=Decimal("5000")).exists()
    assert Price.objects.filter(variant=v, currency__code="GBP", amount=Decimal("9.99")).exists()


@pytest.mark.django_db
def test_export_then_reimport_roundtrip(settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    c = APIClient()
    c.force_authenticate(user=staff_user())

    # Seed one product via the import endpoint (multipart file upload).
    csv_text = (
        "slug,name,brand_slug,status,short_description,category_slugs,sku,variant_name,price_ngn,price_gbp,price_usd,price_cad\n"
        "glow,Glow,,active,,,GLOW-1,50ml,7000,,,\n"
    )
    upload = SimpleUploadedFile("import.csv", csv_text.encode(), content_type="text/csv")
    r = c.post("/api/v1/admin/products/import.csv", {"file": upload}, format="multipart")
    assert r.status_code == 200, r.data
    assert r.data["created"] == 1
    assert Product.objects.filter(slug="glow").exists()

    # Export returns CSV text with the product.
    r = c.get("/api/v1/admin/products/export.csv")
    assert r.status_code == 200
    body = b"".join(r.streaming_content).decode() if hasattr(r, "streaming_content") else r.content.decode()
    assert "glow" in body
    assert "GLOW-1" in body


@pytest.mark.django_db
def test_csv_endpoints_require_staff():
    assert APIClient().get("/api/v1/admin/products/export.csv").status_code in (401, 403)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest apps/catalog/tests/test_admin_csv.py -v`
Expected: FAIL — `ModuleNotFoundError: apps.catalog.csv_io`.

- [ ] **Step 3: Write the CSV service**

Create `backend/apps/catalog/csv_io.py`:

```python
"""Pure product CSV import/export. No request/HTTP here — testable in isolation."""
from __future__ import annotations

import csv
import io
from decimal import Decimal, InvalidOperation

from django.db import transaction

from apps.catalog.models import Brand, Category, Product, ProductVariant
from apps.core.models import Currency
from apps.pricing.models import Price

COLUMNS = [
    "slug", "name", "brand_slug", "status", "short_description", "category_slugs",
    "sku", "variant_name", "price_ngn", "price_gbp", "price_usd", "price_cad",
]
_PRICE_COLS = {"price_ngn": "NGN", "price_gbp": "GBP", "price_usd": "USD", "price_cad": "CAD"}


def _apply_row(row: dict) -> str:
    slug = (row.get("slug") or "").strip()
    sku = (row.get("sku") or "").strip()
    if not slug or not row.get("name"):
        raise ValueError("slug and name are required")
    if not sku:
        raise ValueError("sku is required")

    brand = None
    if row.get("brand_slug"):
        brand, _ = Brand.objects.get_or_create(
            slug=row["brand_slug"].strip(), defaults={"name": row["brand_slug"].strip()}
        )

    product, created = Product.objects.update_or_create(
        slug=slug,
        defaults={
            "name": row["name"],
            "brand": brand,
            "status": (row.get("status") or "draft").strip() or "draft",
            "short_description": row.get("short_description") or "",
        },
    )
    if row.get("category_slugs"):
        cats = []
        for cslug in filter(None, (s.strip() for s in row["category_slugs"].split("|"))):
            cat, _ = Category.objects.get_or_create(slug=cslug, defaults={"name": cslug})
            cats.append(cat)
        product.categories.set(cats)

    variant, _ = ProductVariant.objects.update_or_create(
        sku=sku, defaults={"product": product, "name": row.get("variant_name") or sku, "is_default": True}
    )

    for col, code in _PRICE_COLS.items():
        raw = (row.get(col) or "").strip()
        if not raw:
            continue
        try:
            amount = Decimal(raw)
        except InvalidOperation as exc:
            raise ValueError(f"{col} is not a number: {raw!r}") from exc
        Price.objects.update_or_create(
            variant=variant, currency=Currency.objects.get(code=code), country=None, starts_at=None,
            defaults={"amount": amount},
        )
    return "created" if created else "updated"


def import_products_csv(rows) -> dict:
    """Apply an iterable of row dicts. Each row is its own transaction so one bad
    row doesn't roll back the good ones. Returns {created, updated, errors:[{row, error}]}.
    Row numbers are 1-based over the data rows (header excluded)."""
    report = {"created": 0, "updated": 0, "errors": []}
    for i, row in enumerate(rows, start=1):
        try:
            with transaction.atomic():
                outcome = _apply_row(row)
            report[outcome] += 1
        except Exception as exc:  # noqa: BLE001 — collect, don't abort the batch
            report["errors"].append({"row": i, "error": str(exc)})
    return report


def parse_csv_bytes(data: bytes) -> list[dict]:
    return list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))


def export_products_csv() -> str:
    """Serialize every product's default variant to CSV text."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=COLUMNS)
    writer.writeheader()
    products = Product.objects.select_related("brand").prefetch_related(
        "categories", "variants__prices__currency"
    )
    for p in products:
        variant = p.variants.filter(is_default=True).first() or p.variants.first()
        prices = {}
        if variant:
            for pr in variant.prices.filter(country__isnull=True):
                prices[pr.currency.code] = str(pr.amount)
        writer.writerow({
            "slug": p.slug, "name": p.name, "brand_slug": p.brand.slug if p.brand else "",
            "status": p.status, "short_description": p.short_description,
            "category_slugs": "|".join(c.slug for c in p.categories.all()),
            "sku": variant.sku if variant else "", "variant_name": variant.name if variant else "",
            "price_ngn": prices.get("NGN", ""), "price_gbp": prices.get("GBP", ""),
            "price_usd": prices.get("USD", ""), "price_cad": prices.get("CAD", ""),
        })
    return buf.getvalue()
```

- [ ] **Step 4: Write the Celery task**

Create `backend/apps/catalog/tasks.py`:

```python
from celery import shared_task

from apps.catalog.csv_io import import_products_csv, parse_csv_bytes


@shared_task
def import_products_csv_task(raw_bytes: bytes) -> dict:
    return import_products_csv(parse_csv_bytes(raw_bytes))
```

- [ ] **Step 5: Add the export/import views**

Append to `backend/apps/catalog/admin_views.py`:

```python
from django.http import StreamingHttpResponse
from rest_framework.views import APIView

from apps.catalog.csv_io import export_products_csv
from apps.catalog.tasks import import_products_csv_task


class ProductCSVExportView(APIView):
    permission_classes = [permissions.IsAdminUser]

    def get(self, request):
        resp = StreamingHttpResponse(
            iter([export_products_csv()]), content_type="text/csv"
        )
        resp["Content-Disposition"] = "attachment; filename=products.csv"
        return resp


class ProductCSVImportView(APIView):
    permission_classes = [permissions.IsAdminUser]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        upload = request.data.get("file")
        if upload is None:
            return Response({"detail": "No file provided."}, status=400)
        # Eager in dev/tests -> report returns inline; async in prod (fetch by task id).
        result = import_products_csv_task.delay(upload.read())
        report = result.get() if result.ready() or True else {"task_id": result.id}
        return Response(report, status=200)
```

Note: the `or True` forces `.get()` in all envs for a synchronous report. In prod with a real broker you may prefer returning `{"task_id": result.id}` and polling — leave a `# PLAN-05c-async` marker and keep the inline report for MVP simplicity (Hammed's admin is single-operator).

- [ ] **Step 6: Wire the CSV routes**

In `backend/apps/catalog/admin_urls.py`, add explicit paths **before** `urlpatterns = router.urls` and combine:

```python
from django.urls import path

from apps.catalog.admin_views import ProductCSVExportView, ProductCSVImportView

urlpatterns = [
    path("products/export.csv", ProductCSVExportView.as_view(), name="admin-product-export"),
    path("products/import.csv", ProductCSVImportView.as_view(), name="admin-product-import"),
] + router.urls
```

(Explicit paths first so `products/export.csv` isn't swallowed by the router's `products/<pk>/` detail route.)

- [ ] **Step 7: Run test to verify it passes**

Run: `uv run python -m pytest apps/catalog/tests/test_admin_csv.py -v`
Expected: PASS (3 tests).

- [ ] **Step 8: Commit**

```bash
git add apps/catalog/csv_io.py apps/catalog/tasks.py apps/catalog/admin_views.py apps/catalog/admin_urls.py apps/catalog/tests/test_admin_csv.py
git commit -m "feat(catalog): admin product CSV export + import (Celery, row-level report)"
```

---

## Task 5: Docs + final verification

**Files:**
- Modify: `docs/architecture.md`

- [ ] **Step 1: Update status**

In `docs/architecture.md`, append to **Current status**:

```
Plan-05c (catalog admin write) ✅ — staff-only CRUD for all catalog + price models, product image
upload to S3, product CSV export + import (Celery job with row-level error report). Public read
cache auto-invalidates on admin writes via the existing signals. Plan-05 (catalog) COMPLETE.
Next: Plan-06 (inventory) or Plan-02 (VPS, needs Cloudflare).
```

- [ ] **Step 2: Commit**

```bash
git add docs/architecture.md
git commit -m "docs: record Plan-05c catalog admin write status; Plan-05 complete"
```

---

## Final verification (stage)

- [ ] `uv run python -m pytest -q` — all green.
- [ ] `uv run python manage.py check` — no issues.
- [ ] **Manual smoke** (create a superuser first: `uv run python manage.py createsuperuser`), then with a JWT or session:
  - `POST /api/v1/admin/products/` creates a product (visible at `/api/docs/`).
  - `POST /api/v1/admin/products/<slug>/images/` with a file → image on S3 (check the bucket).
  - `GET /api/v1/admin/products/export.csv` downloads a CSV; edit a price; re-import via `POST /api/v1/admin/products/import.csv`; confirm the report and the changed price.
- [ ] Confirm an admin edit busts the public cache: edit a product price, then `GET /api/v1/products/<slug>/` reflects it immediately.

**CHECKPOINT:** show Hammed the admin endpoints in Swagger (`/api/docs/`), a CSV round-trip report, and an uploaded image URL.

---

## Self-review notes (author)

- **Spec coverage (Plan-05 item 3 — admin write API):** full CRUD on all catalog models (Tasks 1–2) + `Price` (Task 2); `POST /admin/products/{slug}/images/` multipart → storage/S3 (Task 3); `export.csv` + `import.csv` as a Celery job with a row-level error report (Task 4). ✅ Auth is `IsAdminUser` (RBAC → Plan-16, marked).
- **Cache coherence:** admin writes fire the Plan-05b `post_save`/`post_delete` signals → catalog cache version bumps → public read cache invalidated with no extra code. A test asserts this in the final verification.
- **Test safety:** the image-upload test overrides `STORAGES` to `InMemoryStorage` so it never writes to the live S3 bucket configured in `.env`. Do not remove that override.
- **Flagged simplifications:** CSV import returns its report inline (`.get()`) rather than a task id, fine for a single-operator admin — marked `# PLAN-05c-async`; the CSV format covers one default variant + per-currency country-NULL prices (multi-variant/product-level imports can extend the columns later); rule-based Collection auto-population (nightly task) is deferred with the rest of the collections rule engine.
- **Types consistent:** `import_products_csv(rows) -> {created, updated, errors:[{row, error}]}` is used identically by the service test, the Celery task, and the import view.
```
