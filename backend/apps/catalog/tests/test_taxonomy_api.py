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
