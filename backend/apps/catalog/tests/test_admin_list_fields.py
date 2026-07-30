"""The read-only columns the admin products list needs — Plan-17a Task 2.

`ProductAdminSerializer` carried no image, no variant count, no sense of which markets a
product is priced for, and not even `updated_at`. A list built on it could show a name and
a status, which is not enough to find a product among 69 without opening each one.

The query budget is the load-bearing test here. All three columns read prefetched
relations, and the failure mode if a prefetch is dropped is invisible in the response —
identical JSON, three queries per row instead of three per page.
"""
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.catalog.factories import PriceFactory, ProductFactory, ProductVariantFactory
from apps.catalog.models import ProductImage
from apps.catalog.tests.factories_admin import staff_user
from apps.core.models import Country, Currency

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def in_memory_media(settings):
    settings.STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }


@pytest.fixture
def admin_client():
    c = APIClient()
    c.force_authenticate(user=staff_user())
    return c


def _row(response, slug):
    return next(row for row in response.data["results"] if row["slug"] == slug)


def test_list_reports_variant_count(admin_client):
    solo = ProductFactory(slug="solo")
    ProductVariantFactory(product=solo)
    multi = ProductFactory(slug="multi")
    ProductVariantFactory(product=multi, sku="M-1")
    ProductVariantFactory(product=multi, sku="M-2", is_default=False)

    r = admin_client.get("/api/v1/admin/products/")

    assert r.status_code == 200, r.data
    assert _row(r, "solo")["variant_count"] == 1
    assert _row(r, "multi")["variant_count"] == 2


def test_list_reports_a_thumbnail_and_none_when_there_is_no_image(admin_client):
    with_image = ProductFactory(slug="with-image")
    ProductImage.objects.create(
        product=with_image, image="catalog/products/a.png", position=0
    )
    ProductFactory(slug="no-image")

    r = admin_client.get("/api/v1/admin/products/")

    assert r.status_code == 200, r.data
    assert _row(r, "with-image")["thumbnail"] is not None
    assert _row(r, "no-image")["thumbnail"] is None


def test_the_thumbnail_is_the_first_image_by_position(admin_client):
    """The same image the storefront leads with — that is what makes a row recognisable
    to somebody who knows the product by sight rather than by SKU."""
    p = ProductFactory(slug="ordered")
    ProductImage.objects.create(product=p, image="catalog/products/second.png", position=5)
    ProductImage.objects.create(product=p, image="catalog/products/first.png", position=1)

    r = admin_client.get("/api/v1/admin/products/")

    assert "first.png" in _row(r, "ordered")["thumbnail"]


def test_priced_currencies_lists_only_currencies_with_a_price(admin_client):
    p = ProductFactory(slug="ngn-only")
    v = ProductVariantFactory(product=p)
    PriceFactory(variant=v, amount=Decimal("5000.00"))  # NGN

    r = admin_client.get("/api/v1/admin/products/")

    assert _row(r, "ngn-only")["priced_currencies"] == ["NGN"]


def test_priced_currencies_is_empty_when_nothing_is_priced(admin_client):
    p = ProductFactory(slug="unpriced")
    ProductVariantFactory(product=p)

    r = admin_client.get("/api/v1/admin/products/")

    assert _row(r, "unpriced")["priced_currencies"] == []


def test_a_country_override_does_not_count_as_pricing_the_currency(admin_client):
    """A country-level row (`Price.country` non-NULL) prices ONE country, not the whole
    currency. Counting it as the latter would show a product as priced for a market it is
    still invisible in — and "invisible for want of a price" is exactly what this column
    exists to surface. Production has no overrides today; this must not be the code that
    assumes it never will."""
    p = ProductFactory(slug="override-only")
    v = ProductVariantFactory(product=p)
    PriceFactory(
        variant=v,
        amount=Decimal("40.00"),
        currency=Currency.objects.get(code="GBP"),
        country=Country.objects.get(code="GB"),
    )

    r = admin_client.get("/api/v1/admin/products/")

    assert _row(r, "override-only")["priced_currencies"] == []


def test_list_reports_updated_at(admin_client):
    ProductFactory(slug="stamped")

    r = admin_client.get("/api/v1/admin/products/")

    assert _row(r, "stamped")["updated_at"] is not None


def test_the_list_does_not_scale_its_queries_with_the_row_count(
    admin_client, django_assert_max_num_queries
):
    """THE test that keeps the three new columns cheap.

    Each reads a related set, so without `prefetch_related` a 24-row page costs three
    queries per row and the JSON looks identical either way. Twelve products, each with
    two variants, two prices and an image — a budget that a per-row query cannot fit
    under, and that a prefetched page clears with room to spare.

    MEASURED: 11 queries prefetched, 55 without. The budget is 12 rather than 11 so a
    harmless extra (a savepoint, an auth lookup) does not fail the build, while a
    reintroduced per-row query — which starts at 55 — cannot possibly slip under it.
    """
    for i in range(12):
        p = ProductFactory(slug=f"budget-{i}")
        ProductImage.objects.create(product=p, image=f"catalog/products/{i}.png")
        for j in range(2):
            v = ProductVariantFactory(product=p, sku=f"B-{i}-{j}", is_default=j == 0)
            PriceFactory(variant=v, amount=Decimal("100.00"))

    with django_assert_max_num_queries(12):
        r = admin_client.get("/api/v1/admin/products/")

    assert r.status_code == 200
    assert r.data["count"] == 12


def test_the_write_response_still_renders_without_the_prefetch(admin_client):
    """A create returns a plain instance with nothing prefetched. This is why the three
    columns are SerializerMethodFields over relations and not queryset annotations — an
    annotated field renders on the list and then raises AttributeError here."""
    r = admin_client.post(
        "/api/v1/admin/products/", {"name": "Fresh", "slug": "fresh"}, format="json"
    )

    assert r.status_code == 201, r.data
    assert r.data["variant_count"] == 0
    assert r.data["thumbnail"] is None
    assert r.data["priced_currencies"] == []
