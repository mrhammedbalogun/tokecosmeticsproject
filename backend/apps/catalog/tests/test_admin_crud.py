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
