"""Filtering and search on the catalogue admin viewsets — Plan-17a Task 1.

None of this existed before 17a: not one catalogue admin viewset carried a
`filter_backends`, a `filterset_fields` or a `search_fields`. The global default is
`DjangoFilterBackend`, but a view with no `filterset_fields` filters nothing, and
`SearchFilter` was not in the global list at all.

Three screens need it (`docs/superpowers/plans/2026-07-30-plan-17a-admin-catalog.md`):
the products list needs search + a status facet; the editor's Variants tab needs ONE
product's variants; the Prices grid needs ONE product's prices. Without these the admin
would fetch the whole catalogue and narrow it in the browser, which ships every row into
the RSC payload whether or not it is rendered — the Plan-16 Task 8 finding.
"""
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.catalog.factories import PriceFactory, ProductFactory, ProductVariantFactory
from apps.catalog.tests.factories_admin import staff_user


@pytest.fixture
def admin_client():
    c = APIClient()
    c.force_authenticate(user=staff_user())
    return c


def _slugs(response):
    return {row["slug"] for row in response.data["results"]}


# --- products: the status facet ------------------------------------------------------


@pytest.mark.django_db
def test_products_filter_by_status(admin_client):
    ProductFactory(slug="live-one", status="active")
    ProductFactory(slug="draft-one", status="draft")
    ProductFactory(slug="archived-one", status="archived")

    r = admin_client.get("/api/v1/admin/products/?status=draft")

    assert r.status_code == 200, r.data
    assert _slugs(r) == {"draft-one"}


@pytest.mark.django_db
def test_products_unfiltered_list_includes_every_status(admin_client):
    """The admin list is not the storefront list. A draft product is exactly what staff
    come here to find, so the absence of a filter must not imply `status=active`."""
    ProductFactory(slug="live-one", status="active")
    ProductFactory(slug="draft-one", status="draft")
    ProductFactory(slug="archived-one", status="archived")

    r = admin_client.get("/api/v1/admin/products/")

    assert r.status_code == 200, r.data
    assert _slugs(r) == {"live-one", "draft-one", "archived-one"}


# --- products: search ----------------------------------------------------------------


@pytest.mark.django_db
def test_products_search_by_name(admin_client):
    ProductFactory(slug="shea", name="Carrot Shea Butter")
    ProductFactory(slug="shampoo", name="Kids Shampoo")

    r = admin_client.get("/api/v1/admin/products/?search=shea")

    assert r.status_code == 200, r.data
    assert _slugs(r) == {"shea"}


@pytest.mark.django_db
def test_products_search_is_case_insensitive_and_matches_mid_string(admin_client):
    """Staff type the middle of a word as often as the start. `variant_sku_trgm` and
    `product_name_upper_trgm` exist (Plan-16 Task 6) precisely for this shape of lookup."""
    ProductFactory(slug="shea", name="Carrot Shea Butter")

    r = admin_client.get("/api/v1/admin/products/?search=ROT SHE")

    assert r.status_code == 200, r.data
    assert _slugs(r) == {"shea"}


@pytest.mark.django_db
def test_products_search_by_variant_sku(admin_client):
    """The product list is searched by SKU because that is what staff read off a jar,
    and a SKU belongs to a variant, not to the product."""
    p = ProductFactory(slug="oil", name="Hair Grow Oil")
    ProductVariantFactory(product=p, sku="TC-WP-4123")
    ProductFactory(slug="other", name="Something Else")

    r = admin_client.get("/api/v1/admin/products/?search=4123")

    assert r.status_code == 200, r.data
    assert _slugs(r) == {"oil"}


@pytest.mark.django_db
def test_search_returns_a_multi_variant_product_exactly_once(admin_client):
    """THE row-multiplication guard. Searching across a reverse FK join yields one row
    per matching variant unless the backend de-duplicates. 18 of 69 production products
    are multi-variant, so a duplicate here is not an edge case — it is a quarter of the
    catalogue rendering twice."""
    p = ProductFactory(slug="senator", name="Senator Fabric")
    ProductVariantFactory(product=p, sku="MATCHME-50", is_default=True)
    ProductVariantFactory(product=p, sku="MATCHME-100", is_default=False)

    r = admin_client.get("/api/v1/admin/products/?search=MATCHME")

    assert r.status_code == 200, r.data
    assert [row["slug"] for row in r.data["results"]] == ["senator"]
    assert r.data["count"] == 1


@pytest.mark.django_db
def test_products_search_combines_with_the_status_filter(admin_client):
    """Both backends must be active at once. Listing `filter_backends` on a view REPLACES
    the global default, so it is genuinely possible to add SearchFilter and silently lose
    DjangoFilterBackend."""
    ProductFactory(slug="draft-shea", name="Carrot Shea Butter", status="draft")
    ProductFactory(slug="live-shea", name="Shea Body Cream", status="active")

    r = admin_client.get("/api/v1/admin/products/?search=shea&status=draft")

    assert r.status_code == 200, r.data
    assert _slugs(r) == {"draft-shea"}


# --- variants ------------------------------------------------------------------------


@pytest.mark.django_db
def test_variants_filter_by_product(admin_client):
    wanted = ProductFactory(slug="wanted")
    other = ProductFactory(slug="other")
    ProductVariantFactory(product=wanted, sku="WANT-1")
    ProductVariantFactory(product=wanted, sku="WANT-2", is_default=False)
    ProductVariantFactory(product=other, sku="OTHER-1")

    r = admin_client.get(f"/api/v1/admin/variants/?product={wanted.id}")

    assert r.status_code == 200, r.data
    assert {row["sku"] for row in r.data["results"]} == {"WANT-1", "WANT-2"}


@pytest.mark.django_db
def test_variants_filter_by_is_active(admin_client):
    p = ProductFactory()
    ProductVariantFactory(product=p, sku="ON", is_active=True)
    ProductVariantFactory(product=p, sku="OFF", is_active=False, is_default=False)

    r = admin_client.get(f"/api/v1/admin/variants/?product={p.id}&is_active=false")

    assert r.status_code == 200, r.data
    assert {row["sku"] for row in r.data["results"]} == {"OFF"}


# --- prices --------------------------------------------------------------------------


@pytest.mark.django_db
def test_prices_filter_by_variant(admin_client):
    p = ProductFactory()
    wanted = ProductVariantFactory(product=p, sku="WANT")
    other = ProductVariantFactory(product=p, sku="OTHER", is_default=False)
    PriceFactory(variant=wanted, amount=Decimal("1000.00"))
    PriceFactory(variant=other, amount=Decimal("2000.00"))

    r = admin_client.get(f"/api/v1/admin/prices/?variant={wanted.id}")

    assert r.status_code == 200, r.data
    assert [row["amount"] for row in r.data["results"]] == ["1000.00"]


@pytest.mark.django_db
def test_prices_filter_by_currency(admin_client):
    """The Prices grid is variant x currency. Fetching one column at a time is how it
    fills a cell it knows is empty."""
    p = ProductFactory()
    v = ProductVariantFactory(product=p)
    PriceFactory(variant=v, amount=Decimal("1000.00"))  # NGN

    r = admin_client.get(f"/api/v1/admin/prices/?variant={v.id}&currency=NGN")
    assert r.status_code == 200, r.data
    assert r.data["count"] == 1

    r = admin_client.get(f"/api/v1/admin/prices/?variant={v.id}&currency=GBP")
    assert r.status_code == 200, r.data
    assert r.data["count"] == 0
