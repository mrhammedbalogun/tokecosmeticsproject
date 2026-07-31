"""Category parenting cannot create a cycle — Plan-17a Task 10.

Nothing prevented this before. `Category.parent` is a plain self-FK with no `clean()` and
no database constraint, so one PATCH could make a category its own ancestor — and the
damage lands on the PUBLIC storefront, not on the admin:

* `Category.get_ancestors()` walked `node = node.parent` with no exit but `None`;
* `api_serializers.CategorySerializer.get_children` recurses into itself.

Either is a hung worker. The admin's category page is what would have made it reachable,
so the guard ships with that page.
"""
import pytest
from rest_framework.test import APIClient

from apps.catalog.factories import CategoryFactory
from apps.catalog.models import Category
from apps.catalog.tests.factories_admin import staff_user

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_client():
    c = APIClient()
    c.force_authenticate(user=staff_user())
    return c


def test_a_category_cannot_be_its_own_parent(admin_client):
    category = CategoryFactory(slug="skincare")

    r = admin_client.patch(
        f"/api/v1/admin/categories/{category.slug}/", {"parent": category.id}, format="json"
    )

    assert r.status_code == 400, r.data
    assert "parent" in r.data
    category.refresh_from_db()
    assert category.parent_id is None


def test_a_category_cannot_be_parented_to_its_own_child(admin_client):
    parent = CategoryFactory(slug="skincare")
    child = CategoryFactory(slug="cleansers", parent=parent)

    r = admin_client.patch(
        f"/api/v1/admin/categories/{parent.slug}/", {"parent": child.id}, format="json"
    )

    assert r.status_code == 400, r.data
    parent.refresh_from_db()
    assert parent.parent_id is None


def test_a_category_cannot_be_parented_to_a_deeper_descendant(admin_client):
    """Two levels down, because a check that only looked at direct children would pass
    this and still produce a cycle."""
    root = CategoryFactory(slug="root")
    mid = CategoryFactory(slug="mid", parent=root)
    leaf = CategoryFactory(slug="leaf", parent=mid)

    r = admin_client.patch(
        f"/api/v1/admin/categories/{root.slug}/", {"parent": leaf.id}, format="json"
    )

    assert r.status_code == 400, r.data
    root.refresh_from_db()
    assert root.parent_id is None


def test_the_message_names_both_categories(admin_client):
    parent = CategoryFactory(slug="skincare", name="Skincare")
    child = CategoryFactory(slug="cleansers", name="Cleansers", parent=parent)

    r = admin_client.patch(
        f"/api/v1/admin/categories/{parent.slug}/", {"parent": child.id}, format="json"
    )

    message = str(r.data["parent"])
    assert "Cleansers" in message and "Skincare" in message


def test_a_legitimate_reparent_still_works(admin_client):
    """The guard must not refuse the ordinary case it sits next to."""
    a = CategoryFactory(slug="a")
    b = CategoryFactory(slug="b")

    r = admin_client.patch(f"/api/v1/admin/categories/{b.slug}/", {"parent": a.id}, format="json")

    assert r.status_code == 200, r.data
    b.refresh_from_db()
    assert b.parent_id == a.id


def test_moving_a_category_to_a_root_still_works(admin_client):
    parent = CategoryFactory(slug="p")
    child = CategoryFactory(slug="c", parent=parent)

    r = admin_client.patch(
        f"/api/v1/admin/categories/{child.slug}/", {"parent": None}, format="json"
    )

    assert r.status_code == 200, r.data
    child.refresh_from_db()
    assert child.parent_id is None


def test_creating_a_category_under_an_existing_one_still_works(admin_client):
    parent = CategoryFactory(slug="p")

    r = admin_client.post(
        "/api/v1/admin/categories/",
        {"name": "New", "slug": "new", "parent": parent.id},
        format="json",
    )

    assert r.status_code == 201, r.data


def test_get_ancestors_terminates_on_a_cycle_already_in_the_data():
    """Defence in depth for a row the validator never saw — a direct database edit, a
    fixture, or anything written before the guard existed. A short breadcrumb is a bad
    answer; an unresponsive worker is not an answer at all."""
    a = CategoryFactory(slug="a")
    b = CategoryFactory(slug="b", parent=a)
    # Written straight to the column, bypassing the serializer entirely.
    Category.objects.filter(pk=a.pk).update(parent=b)
    a.refresh_from_db()

    ancestors = a.get_ancestors()

    assert len(ancestors) <= 2
