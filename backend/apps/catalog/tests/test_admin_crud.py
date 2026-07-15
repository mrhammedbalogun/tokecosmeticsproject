import pytest
from rest_framework.test import APIClient

from apps.catalog.models import Product
from apps.catalog.tests.factories_admin import staff_user


@pytest.mark.django_db
def test_admin_price_edit_busts_public_cache(settings):
    """An admin price change must invalidate the cached public product response."""
    from decimal import Decimal

    settings.CACHES = {
        "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "inv"}
    }
    from django.core.cache import cache

    from apps.catalog.factories import PriceFactory, ProductFactory, ProductVariantFactory

    cache.clear()
    p = ProductFactory(slug="cached")
    v = ProductVariantFactory(product=p)
    price = PriceFactory(variant=v, amount=Decimal("1000"))

    pub = APIClient()
    r = pub.get("/api/v1/products/cached/", HTTP_X_COUNTRY="NG")
    assert r.data["variants"][0]["price"]["amount"] == "1000.00"  # now cached

    # Staff edits the price -> post_save signal bumps the catalog cache version.
    admin = APIClient()
    admin.force_authenticate(user=staff_user())
    r = admin.patch(f"/api/v1/admin/prices/{price.id}/", {"amount": "1500.00"}, format="json")
    assert r.status_code == 200

    r = pub.get("/api/v1/products/cached/", HTTP_X_COUNTRY="NG")
    assert r.data["variants"][0]["price"]["amount"] == "1500.00"  # cache invalidated


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
    from decimal import Decimal

    assert Decimal(price.data["amount"]) == Decimal("5000.00")
